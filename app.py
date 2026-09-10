import os, json, secrets
from datetime import datetime
from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER', '').lower() == 'true'

db_url = os.getenv('DATABASE_URL', 'sqlite:///transformacao_kaz.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
if db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    __tablename__ = 'kaz_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='owner')  # admin, direction, owner
    project_id = db.Column(db.String(80), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AppState(db.Model):
    __tablename__ = 'kaz_app_state'
    id = db.Column(db.Integer, primary_key=True, default=1)
    payload = db.Column(db.JSON, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    updated_by = db.Column(db.String(160))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Attachment(db.Model):
    __tablename__ = 'kaz_attachments'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(80), nullable=False, index=True)
    milestone_id = db.Column(db.String(120), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    note = db.Column(db.String(500))
    mime_type = db.Column(db.String(180))
    size = db.Column(db.Integer, nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_by = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

OWNER_SEEDS = [
    ('ana','Ana Silvia','owner','comercial'),
    ('oscar','Oscar','owner','projetos'),
    ('raquel','Raquel','owner','posvenda'),
    ('ju','Ju Hirota','owner','producao'),
    ('wancler','Wancler','owner','compras'),
    ('erik','Erik','owner','financeiro'),
    ('vini','Vini','owner','planejamento'),
    ('marcio','Márcio','direction',None),
    ('marcinho','Marcinho','direction',None),
    ('leo','Leo','direction',None),
]

def load_seed():
    path = os.path.join(app.root_path, 'seed_state.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def seed_if_empty():
    state = db.session.get(AppState, 1)
    if not state:
        db.session.add(AppState(id=1, payload=load_seed(), revision=1, updated_by='Sistema'))

    admin_username = os.getenv('ADMIN_USERNAME', 'rachid').strip().lower()
    admin_password = os.getenv('ADMIN_PASSWORD')
    if not admin_password:
        admin_password = 'change-me-now'
    admin = User.query.filter_by(username=admin_username).first()
    if not admin:
        db.session.add(User(
            username=admin_username,
            display_name='Rachid',
            password_hash=generate_password_hash(admin_password),
            role='admin', active=True
        ))

    # Pre-create the known participants, but keep them inactive until the admin defines passwords.
    for username, display_name, role, project_id in OWNER_SEEDS:
        if not User.query.filter_by(username=username).first():
            db.session.add(User(
                username=username,
                display_name=display_name,
                password_hash=generate_password_hash(secrets.token_urlsafe(32)),
                role=role, project_id=project_id, active=False
            ))
    db.session.commit()

def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not u.active:
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify({'error':'unauthorized'}), 401
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user().role != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def require_csrf():
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token or not secrets.compare_digest(token, session.get('csrf','')):
        abort(403)

def public_user(u):
    return {
        'id':u.id, 'username':u.username, 'display_name':u.display_name,
        'role':u.role, 'project_id':u.project_id, 'active':u.active
    }


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',',':'))

def enforce_owner_state_change(old, new, u):
    """Owners may edit their project, create meetings/dependencies from it,
    and update dependencies assigned to them. Direction/admin may edit everything."""
    if u.role in ('admin','direction'):
        return
    if u.role != 'owner' or not u.project_id:
        abort(403)

    old_projects = {p.get('id'):p for p in old.get('projects',[])}
    new_projects = {p.get('id'):p for p in new.get('projects',[])}
    if set(old_projects) != set(new_projects):
        abort(403)
    for pid, oldp in old_projects.items():
        if pid != u.project_id and canonical(oldp) != canonical(new_projects[pid]):
            abort(403)

    old_meetings = {str(m.get('id')):m for m in old.get('meetings',[])}
    for m in new.get('meetings',[]):
        mid=str(m.get('id'))
        if mid in old_meetings:
            if canonical(m) != canonical(old_meetings[mid]):
                abort(403)
        elif m.get('projectId') != u.project_id:
            abort(403)
    if any(str(mid) not in {str(m.get('id')) for m in new.get('meetings',[])} for mid in old_meetings):
        abort(403)

    old_deps = {str(d.get('id')):d for d in old.get('dependencies',[])}
    new_dep_ids=set()
    uname=(u.display_name or '').strip().casefold()
    for d in new.get('dependencies',[]):
        did=str(d.get('id')); new_dep_ids.add(did)
        if did not in old_deps:
            if d.get('projectId') != u.project_id:
                abort(403)
        elif canonical(d) != canonical(old_deps[did]):
            oldd=old_deps[did]
            assigned=(oldd.get('person') or '').strip().casefold()==uname
            own=oldd.get('projectId')==u.project_id
            if not (assigned or own):
                abort(403)
    if any(did not in new_dep_ids for did in old_deps):
        abort(403)

@app.route('/health')
def health():
    return jsonify({'ok': True, 'service':'transformacao-kaz'})

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user() and current_user().active:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username','').strip().lower()
        password = request.form.get('password','')
        u = User.query.filter_by(username=username).first()
        if u and u.active and check_password_hash(u.password_hash, password):
            session.clear()
            session['user_id'] = u.id
            session['csrf'] = secrets.token_urlsafe(24)
            return redirect(url_for('index'))
        error = 'Usuário ou senha inválidos.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    state = db.session.get(AppState, 1)
    return render_template(
        'index.html',
        initial_state=state.payload,
        revision=state.revision,
        user=public_user(current_user()),
        csrf=session['csrf']
    )

@app.route('/api/state', methods=['GET'])
@login_required
def api_get_state():
    state = db.session.get(AppState, 1)
    return jsonify({'state':state.payload, 'revision':state.revision, 'updated_by':state.updated_by,
                    'updated_at':state.updated_at.isoformat() if state.updated_at else None})

@app.route('/api/state', methods=['POST'])
@login_required
def api_save_state():
    require_csrf()
    body = request.get_json(force=True)
    payload = body.get('state')
    client_revision = int(body.get('revision', 0))
    if not isinstance(payload, dict) or not isinstance(payload.get('projects'), list):
        return jsonify({'error':'invalid_state'}), 400

    # PostgreSQL locks the single state row during the revision check/update.
    state = db.session.execute(select(AppState).where(AppState.id==1).with_for_update()).scalar_one()
    if client_revision != state.revision:
        return jsonify({'error':'conflict','revision':state.revision,'state':state.payload}), 409

    enforce_owner_state_change(state.payload, payload, current_user())
    state.payload = payload
    state.revision += 1
    state.updated_by = current_user().display_name
    state.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok':True, 'revision':state.revision})

@app.route('/api/attachments', methods=['POST'])
@login_required
def upload_attachment():
    require_csrf()
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error':'missing_file'}), 400
    data = f.read()
    if len(data) > 12 * 1024 * 1024:
        return jsonify({'error':'too_large'}), 413
    name = secure_filename(f.filename) or 'arquivo'
    project_id=request.form.get('project_id','')
    u=current_user()
    if u.role=='owner' and project_id != u.project_id:
        abort(403)
    a = Attachment(
        project_id=project_id,
        milestone_id=request.form.get('milestone_id') or None,
        name=name,
        note=request.form.get('note','').strip(),
        mime_type=f.mimetype,
        size=len(data), file_data=data,
        uploaded_by=current_user().display_name
    )
    db.session.add(a); db.session.commit()
    return jsonify({
        'id':a.id, 'name':a.name, 'size':a.size, 'note':a.note,
        'date':a.created_at.strftime('%d/%m/%Y %H:%M'),
        'url':url_for('download_attachment', attachment_id=a.id)
    })

@app.route('/attachments/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    a = db.session.get(Attachment, attachment_id)
    if not a: abort(404)
    return send_file(BytesIO(a.file_data), mimetype=a.mime_type or 'application/octet-stream',
                     as_attachment=True, download_name=a.name)

@app.route('/api/users')
@login_required
def api_users():
    return jsonify([public_user(u) for u in User.query.order_by(User.display_name).all()])

@app.route('/admin/users', methods=['GET','POST'])
@admin_required
def admin_users():
    message = None; error = None
    if request.method == 'POST':
        require_csrf()
        uid = int(request.form['user_id'])
        u = db.session.get(User, uid)
        if not u: abort(404)
        u.display_name = request.form.get('display_name',u.display_name).strip() or u.display_name
        u.role = request.form.get('role',u.role)
        u.project_id = request.form.get('project_id') or None
        u.active = request.form.get('active') == 'on'
        password = request.form.get('password','')
        if password:
            if len(password) < 8:
                error = 'A senha precisa ter pelo menos 8 caracteres.'
            else:
                u.password_hash = generate_password_hash(password)
        if not error:
            db.session.commit(); message = f'Usuário {u.display_name} atualizado.'
    users = User.query.order_by(User.display_name).all()
    state = db.session.get(AppState,1).payload
    projects = [(p['id'],p['name']) for p in state.get('projects',[])]
    return render_template('users.html', users=users, projects=projects, csrf=session['csrf'], message=message, error=error)

with app.app_context():
    db.create_all()
    seed_if_empty()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5000')), debug=os.getenv('FLASK_DEBUG')=='1')
