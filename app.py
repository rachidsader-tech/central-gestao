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

PROJECT_STATUSES = ['Não iniciado', 'Em andamento', 'Em risco', 'Concluído']
MILESTONE_STATUSES = ['Não iniciado', 'Em andamento', 'Em risco', 'Concluído']
DEPENDENCY_STATUSES = ['Aberta', 'Em análise', 'Respondida', 'Resolvida']
DIRECTORS = ['Rachid', 'Leo', 'Márcio', 'Marcinho']

class User(db.Model):
    __tablename__ = 'kaz_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='owner')
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
    dependency_id = db.Column(db.String(120), nullable=True, index=True)
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

def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')

def load_seed():
    with open(os.path.join(app.root_path, 'seed_state.json'), encoding='utf-8') as f:
        return json.load(f)

def event(kind, actor, text='', **extra):
    item = {'id': secrets.token_hex(8), 'at': now_iso(), 'kind': kind, 'actor': actor, 'text': text}
    item.update(extra)
    return item

def migrate_payload(payload):
    changed = False
    if not isinstance(payload, dict):
        payload = load_seed(); changed = True
    if payload.get('schemaVersion', 1) < 2:
        payload['schemaVersion'] = 2; changed = True
    payload.setdefault('dependencies', [])
    payload.setdefault('meetings', [])
    payload['direction'] = DIRECTORS[:]
    for p in payload.get('projects', []):
        if p.get('status') not in PROJECT_STATUSES:
            p['status'] = 'Não iniciado'; changed = True
        p.setdefault('weeklyCommitments', [])
        p.setdefault('generalMemos', [])
        p.setdefault('files', [])
        p.setdefault('validated', False)
        if p.get('id') == 'comercial' and payload.get('commercialValidationReset') is not True:
            p['validated'] = False
            p['status'] = 'Não iniciado'
            changed = True
        for m in p.get('milestones', []):
            if m.get('status') not in MILESTONE_STATUSES:
                m['status'] = 'Não iniciado'; changed = True
            m.setdefault('memos', []); m.setdefault('files', []); m.setdefault('conclusion', ''); m.setdefault('concludedAt', '')
    if payload.get('commercialValidationReset') is not True:
        payload['commercialValidationReset'] = True; changed = True
    for d in payload.get('dependencies', []):
        if d.get('status') not in DEPENDENCY_STATUSES:
            d['status'] = 'Aberta'; changed = True
        if d.get('director') not in DIRECTORS:
            d['director'] = 'Rachid'; changed = True
        d.setdefault('history', [])
        d.setdefault('messages', [])
        d.setdefault('files', [])
        d.setdefault('deadline', '')
    return payload, changed

def seed_if_empty():
    state = db.session.get(AppState, 1)
    if not state:
        payload, _ = migrate_payload(load_seed())
        db.session.add(AppState(id=1, payload=payload, revision=1, updated_by='Sistema'))
    else:
        payload, changed = migrate_payload(state.payload)
        if changed:
            state.payload = payload
            state.revision += 1
            state.updated_by = 'Migração V2'
            state.updated_at = datetime.utcnow()
    admin_username = os.getenv('ADMIN_USERNAME', 'rachid').strip().lower()
    admin_password = os.getenv('ADMIN_PASSWORD') or 'change-me-now'
    admin = User.query.filter_by(username=admin_username).first()
    if not admin:
        db.session.add(User(username=admin_username, display_name='Rachid', password_hash=generate_password_hash(admin_password), role='admin', active=True))
    else:
        admin.role='admin'; admin.active=True; admin.display_name='Rachid'; admin.project_id=None
    for username, display_name, role, project_id in OWNER_SEEDS:
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(username=username, display_name=display_name, password_hash=generate_password_hash(secrets.token_urlsafe(32)), role=role, project_id=project_id, active=True)
            db.session.add(u)
        else:
            u.display_name=display_name; u.role=role; u.project_id=project_id; u.active=True
    db.session.commit()

def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None

def public_user(u):
    return {'id':u.id,'username':u.username,'display_name':u.display_name,'role':u.role,'project_id':u.project_id,'active':u.active}

def is_direction(u=None):
    u = u or current_user()
    return bool(u and u.role in ('admin','direction'))

def can_edit_project(project_id, u=None):
    u = u or current_user()
    return bool(u and (is_direction(u) or (u.role=='owner' and u.project_id==project_id)))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u=current_user()
        if not u or not u.active:
            session.clear()
            if request.path.startswith('/api/'): return jsonify({'error':'unauthorized'}),401
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user().role!='admin': abort(403)
        return fn(*args, **kwargs)
    return wrapped

def require_csrf():
    token=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token or not secrets.compare_digest(token, session.get('csrf','')): abort(403)

def locked_state():
    return db.session.execute(select(AppState).where(AppState.id==1).with_for_update()).scalar_one()

def save_state(state, actor):
    state.revision += 1
    state.updated_by = actor
    state.updated_at = datetime.utcnow()
    db.session.commit()
    return state.revision

def find_project(payload, project_id):
    return next((p for p in payload.get('projects',[]) if p.get('id')==project_id), None)

def find_dependency(payload, dep_id):
    return next((d for d in payload.get('dependencies',[]) if str(d.get('id'))==str(dep_id)), None)

@app.route('/health')
def health():
    return jsonify({'ok':True,'service':'transformacao-kaz','version':'2.0'})

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user() and current_user().active: return redirect(url_for('index'))
    error=None
    if request.method=='POST':
        username=request.form.get('username','').strip().lower(); password=request.form.get('password','')
        u=User.query.filter_by(username=username).first()
        if u and u.active and check_password_hash(u.password_hash,password):
            session.clear(); session['user_id']=u.id; session['csrf']=secrets.token_urlsafe(24)
            return redirect(url_for('index'))
        error='Usuário ou senha inválidos.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    state=db.session.get(AppState,1)
    return render_template('index.html', initial_state=state.payload, revision=state.revision, user=public_user(current_user()), csrf=session['csrf'], directors=DIRECTORS)

@app.get('/api/state')
@login_required
def api_state():
    s=db.session.get(AppState,1)
    return jsonify({'state':s.payload,'revision':s.revision,'updated_by':s.updated_by,'updated_at':s.updated_at.isoformat() if s.updated_at else None})

@app.post('/api/projects/<project_id>')
@login_required
def api_project_action(project_id):
    require_csrf(); u=current_user()
    if not can_edit_project(project_id,u): abort(403)
    body=request.get_json(force=True); action=body.get('action')
    state=locked_state(); p=find_project(state.payload, project_id)
    if not p: abort(404)
    actor=u.display_name
    if action=='status':
        status=body.get('status')
        if status not in PROJECT_STATUSES: return jsonify({'error':'invalid_status'}),400
        p['status']=status; p['lastUpdate']=now_iso()
    elif action=='objective':
        p['objective']=str(body.get('objective','')).strip(); p['lastUpdate']=now_iso()
    elif action=='general_memo':
        text=str(body.get('text','')).strip()
        if not text: return jsonify({'error':'empty'}),400
        p.setdefault('generalMemos',[]).append({'id':secrets.token_hex(8),'at':now_iso(),'author':actor,'text':text}); p['lastUpdate']=now_iso()
    elif action=='validated':
        if not is_direction(u): abort(403)
        p['validated']=bool(body.get('value')); p['lastUpdate']=now_iso()
    elif action=='milestone':
        mid=body.get('milestoneId'); m=next((m for m in p.get('milestones',[]) if m.get('id')==mid),None)
        if not m: abort(404)
        if 'status' in body:
            if body['status'] not in MILESTONE_STATUSES: return jsonify({'error':'invalid_status'}),400
            m['status']=body['status']; m['concludedAt']=now_iso() if body['status']=='Concluído' else ''
        if 'deadline' in body: m['deadline']=str(body.get('deadline') or '')
        if 'conclusion' in body: m['conclusion']=str(body.get('conclusion') or '').strip()
        memo=str(body.get('memo') or '').strip()
        if memo: m.setdefault('memos',[]).append({'id':secrets.token_hex(8),'at':now_iso(),'author':actor,'text':memo})
        p['lastUpdate']=now_iso()
    elif action=='weekly_commitment':
        text=str(body.get('text','')).strip()
        if not text: return jsonify({'error':'empty'}),400
        p.setdefault('weeklyCommitments',[]).append({'id':secrets.token_hex(8),'text':text,'status':'Aberto','createdAt':now_iso(),'author':actor})
        p['lastUpdate']=now_iso()
    elif action=='commitment_status':
        cid=str(body.get('commitmentId')); status=body.get('status')
        if status not in ['Aberto','Realizado','Parcial','Não realizado']: return jsonify({'error':'invalid_status'}),400
        c=next((c for c in p.get('weeklyCommitments',[]) if str(c.get('id'))==cid),None)
        if not c: abort(404)
        c['status']=status; c['updatedAt']=now_iso(); c['updatedBy']=actor; p['lastUpdate']=now_iso()
    else:
        return jsonify({'error':'invalid_action'}),400
    rev=save_state(state,actor)
    return jsonify({'ok':True,'revision':rev,'project':p})

@app.post('/api/dependencies')
@login_required
def create_dependency():
    require_csrf(); u=current_user(); body=request.get_json(force=True)
    project_id=body.get('projectId'); director=body.get('director'); subject=str(body.get('subject','')).strip(); description=str(body.get('description','')).strip(); deadline=str(body.get('deadline','')).strip()
    if not can_edit_project(project_id,u): abort(403)
    if director not in DIRECTORS: return jsonify({'error':'invalid_director'}),400
    if not subject or not description: return jsonify({'error':'missing_fields'}),400
    state=locked_state(); p=find_project(state.payload,project_id)
    if not p: abort(404)
    did='dep-'+secrets.token_hex(6); actor=u.display_name
    d={'id':did,'projectId':project_id,'projectName':p.get('name'),'requester':actor,'subject':subject,'description':description,'director':director,'deadline':deadline,'status':'Aberta','createdAt':now_iso(),'updatedAt':now_iso(),'messages':[],'files':[],'history':[event('opened',actor,f'Pendência aberta para {director}.',director=director,deadline=deadline)]}
    state.payload.setdefault('dependencies',[]).append(d)
    rev=save_state(state,actor)
    return jsonify({'ok':True,'revision':rev,'dependency':d})

@app.post('/api/dependencies/<dep_id>/<action>')
@login_required
def dependency_action(dep_id, action):
    require_csrf(); u=current_user(); body=request.get_json(silent=True) or {}; state=locked_state(); d=find_dependency(state.payload,dep_id)
    if not d: abort(404)
    actor=u.display_name; own_project=(u.role=='owner' and u.project_id==d.get('projectId')); direction=is_direction(u); assigned=(actor==d.get('director'))
    if action=='assume':
        if not direction or not assigned: abort(403)
        if d.get('status')!='Aberta': return jsonify({'error':'invalid_transition'}),400
        d['status']='Em análise'; d['history'].append(event('assumed',actor,'Pendência assumida.')); d['updatedAt']=now_iso()
    elif action=='reply':
        if not direction: abort(403)
        text=str(body.get('text','')).strip()
        if not text: return jsonify({'error':'empty'}),400
        final=bool(body.get('final'))
        d.setdefault('messages',[]).append({'id':secrets.token_hex(8),'at':now_iso(),'author':actor,'role':'Diretoria','text':text,'final':final})
        d['history'].append(event('reply',actor,'Resposta da Diretoria registrada.',final=final,textPreview=text[:160]))
        if final: d['status']='Respondida'; d['history'].append(event('status',actor,'Status alterado para Respondida.',fromStatus='Em análise',toStatus='Respondida'))
        elif d.get('status')=='Aberta': d['status']='Em análise'
        d['updatedAt']=now_iso()
    elif action=='comment':
        if not (direction or own_project): abort(403)
        text=str(body.get('text','')).strip()
        if not text: return jsonify({'error':'empty'}),400
        role='Diretoria' if direction else 'Solicitante'
        d.setdefault('messages',[]).append({'id':secrets.token_hex(8),'at':now_iso(),'author':actor,'role':role,'text':text,'final':False})
        d['history'].append(event('comment',actor,'Informação adicionada à pendência.',textPreview=text[:160])); d['updatedAt']=now_iso()
    elif action=='resolve':
        if not (direction or own_project): abort(403)
        if d.get('status')=='Resolvida': return jsonify({'error':'already_resolved'}),400
        note=str(body.get('note','')).strip(); old=d.get('status')
        d['status']='Resolvida'; d['resolvedAt']=now_iso(); d['resolvedBy']=actor; d['resolutionNote']=note
        d['history'].append(event('resolved',actor,'Pendência marcada como resolvida.',fromStatus=old,toStatus='Resolvida',note=note)); d['updatedAt']=now_iso()
    elif action=='reopen':
        if d.get('status')!='Resolvida': return jsonify({'error':'invalid_transition'}),400
        if not (direction or own_project or assigned): abort(403)
        reason=str(body.get('reason','')).strip()
        if not reason: return jsonify({'error':'reason_required'}),400
        d['status']='Em análise'; d['reopenedAt']=now_iso(); d['history'].append(event('reopened',actor,'Pendência reaberta.',reason=reason,fromStatus='Resolvida',toStatus='Em análise')); d['updatedAt']=now_iso()
    elif action=='reassign':
        if not direction: abort(403)
        new_director=body.get('director')
        if new_director not in DIRECTORS: return jsonify({'error':'invalid_director'}),400
        old=d.get('director'); d['director']=new_director; d['history'].append(event('reassigned',actor,f'Diretor responsável alterado de {old} para {new_director}.',fromDirector=old,toDirector=new_director,reason=str(body.get('reason','')).strip())); d['updatedAt']=now_iso()
    elif action=='deadline':
        if not (direction or own_project): abort(403)
        new_deadline=str(body.get('deadline','')).strip(); old=d.get('deadline',''); d['deadline']=new_deadline; d['history'].append(event('deadline',actor,'Prazo alterado.',fromDeadline=old,toDeadline=new_deadline)); d['updatedAt']=now_iso()
    else:
        abort(404)
    rev=save_state(state,actor)
    return jsonify({'ok':True,'revision':rev,'dependency':d})

@app.post('/api/meetings')
@login_required
def create_meeting():
    require_csrf(); u=current_user(); body=request.get_json(force=True); project_id=body.get('projectId')
    if not can_edit_project(project_id,u): abort(403)
    state=locked_state(); p=find_project(state.payload,project_id)
    if not p: abort(404)
    m={'id':'meet-'+secrets.token_hex(6),'projectId':project_id,'projectName':p.get('name'),'at':now_iso(),'createdBy':u.display_name,'notes':str(body.get('notes','')).strip(),'decisions':str(body.get('decisions','')).strip(),'nextWeek':str(body.get('nextWeek','')).strip()}
    state.payload.setdefault('meetings',[]).append(m); p['lastUpdate']=now_iso(); rev=save_state(state,u.display_name)
    return jsonify({'ok':True,'revision':rev,'meeting':m})

@app.post('/api/attachments')
@login_required
def upload_attachment():
    require_csrf(); u=current_user(); f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'missing_file'}),400
    data=f.read()
    if len(data)>12*1024*1024: return jsonify({'error':'too_large'}),413
    project_id=request.form.get('project_id',''); dep_id=request.form.get('dependency_id') or None; milestone_id=request.form.get('milestone_id') or None
    state=db.session.get(AppState,1)
    if dep_id:
        d=find_dependency(state.payload,dep_id)
        if not d: abort(404)
        if not (is_direction(u) or (u.role=='owner' and u.project_id==d.get('projectId'))): abort(403)
        project_id=d.get('projectId')
    elif not can_edit_project(project_id,u):
        abort(403)
    a=Attachment(project_id=project_id,milestone_id=milestone_id,dependency_id=dep_id,name=secure_filename(f.filename) or 'arquivo',note=request.form.get('note','').strip(),mime_type=f.mimetype,size=len(data),file_data=data,uploaded_by=u.display_name)
    db.session.add(a); db.session.commit()
    if dep_id:
        state=locked_state(); d=find_dependency(state.payload,dep_id)
        meta={'id':a.id,'name':a.name,'size':a.size,'date':a.created_at.strftime('%d/%m/%Y %H:%M'),'url':url_for('download_attachment',attachment_id=a.id),'uploadedBy':u.display_name}
        d.setdefault('files',[]).append(meta); d['history'].append(event('file',u.display_name,f'Arquivo anexado: {a.name}',attachmentId=a.id)); save_state(state,u.display_name)
    return jsonify({'id':a.id,'name':a.name,'size':a.size,'date':a.created_at.strftime('%d/%m/%Y %H:%M'),'url':url_for('download_attachment',attachment_id=a.id)})

@app.get('/attachments/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    a=db.session.get(Attachment,attachment_id)
    if not a: abort(404)
    return send_file(BytesIO(a.file_data),mimetype=a.mime_type or 'application/octet-stream',as_attachment=True,download_name=a.name)

@app.get('/api/users')
@login_required
def api_users():
    return jsonify([public_user(u) for u in User.query.order_by(User.display_name).all()])

@app.route('/admin/users', methods=['GET','POST'])
@admin_required
def admin_users():
    message=None; error=None
    if request.method=='POST':
        require_csrf(); uid=int(request.form['user_id']); u=db.session.get(User,uid)
        if not u: abort(404)
        u.display_name=request.form.get('display_name',u.display_name).strip() or u.display_name
        u.role=request.form.get('role',u.role); u.project_id=request.form.get('project_id') or None; u.active=request.form.get('active')=='on'
        password=request.form.get('password','')
        if password:
            if len(password)<8: error='A senha precisa ter pelo menos 8 caracteres.'
            else: u.password_hash=generate_password_hash(password)
        if not error: db.session.commit(); message=f'Usuário {u.display_name} atualizado.'
    users=User.query.order_by(User.display_name).all(); state=db.session.get(AppState,1).payload; projects=[(p['id'],p['name']) for p in state.get('projects',[])]
    return render_template('users.html',users=users,projects=projects,csrf=session['csrf'],message=message,error=error)

with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text
        with db.engine.begin() as conn:
            if db.engine.dialect.name == 'postgresql':
                conn.execute(text("ALTER TABLE kaz_attachments ADD COLUMN IF NOT EXISTS dependency_id VARCHAR(120)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_kaz_attachments_dependency_id ON kaz_attachments (dependency_id)"))
    except Exception:
        pass
    seed_if_empty()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=os.getenv('FLASK_DEBUG')=='1')
