import os, json, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from io import BytesIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
db_url = os.getenv('DATABASE_URL', 'sqlite:///central_gestao.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024

db = SQLAlchemy(app)

class Project(db.Model):
    __tablename__='projects'
    id=db.Column(db.String(120), primary_key=True)
    name=db.Column(db.String(255), nullable=False)
    area=db.Column(db.String(255))
    health=db.Column(db.String(80))
    status=db.Column(db.String(80))
    movement=db.Column(db.Text)
    owner=db.Column(db.String(255))
    priority=db.Column(db.String(50))
    deadline=db.Column(db.String(120))
    deadline_label=db.Column(db.String(120))
    needs_user=db.Column(db.Text)
    objective=db.Column(db.Text)
    done_criteria=db.Column(db.Text)
    current_state=db.Column(db.Text)
    next_action=db.Column(db.Text)
    people=db.Column(db.JSON, default=list)
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
    updated_at=db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Front(db.Model):
    __tablename__='fronts'
    id=db.Column(db.String(160), primary_key=True)
    project_id=db.Column(db.String(120), db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    name=db.Column(db.String(255), nullable=False)
    status=db.Column(db.String(80))
    owner=db.Column(db.String(255))
    next_action=db.Column(db.Text)
    position=db.Column(db.Integer, default=0)

class Task(db.Model):
    __tablename__='tasks'
    id=db.Column(db.String(160), primary_key=True)
    project_id=db.Column(db.String(120), db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    title=db.Column(db.Text, nullable=False)
    owner=db.Column(db.String(255))
    due=db.Column(db.String(120))
    priority=db.Column(db.String(50))
    status=db.Column(db.String(80))
    front=db.Column(db.String(255))
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
    updated_at=db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Note(db.Model):
    __tablename__='notes'
    id=db.Column(db.String(160), primary_key=True)
    title=db.Column(db.String(255), nullable=False)
    body=db.Column(db.Text)
    project=db.Column(db.String(255))
    status=db.Column(db.String(80))
    pinned=db.Column(db.Boolean, default=False)
    created_label=db.Column(db.String(80))
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
    updated_at=db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AgendaEvent(db.Model):
    __tablename__='agenda_events'
    id=db.Column(db.String(160), primary_key=True)
    date=db.Column(db.String(20), nullable=False)
    time_label=db.Column(db.String(80))
    title=db.Column(db.String(255), nullable=False)
    project=db.Column(db.String(255))
    location=db.Column(db.String(255))
    people=db.Column(db.String(500))
    status=db.Column(db.String(80))
    notes=db.Column(db.Text)
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
    updated_at=db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class JournalEntry(db.Model):
    __tablename__='journal_entries'
    id=db.Column(db.Integer, primary_key=True)
    project_id=db.Column(db.String(120), db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    entry_date=db.Column(db.String(20))
    title=db.Column(db.String(255))
    summary=db.Column(db.Text)
    next_action=db.Column(db.Text)
    source=db.Column(db.String(80), default='manual')
    created_at=db.Column(db.DateTime, default=datetime.utcnow)

class Attachment(db.Model):
    __tablename__='attachments'
    id=db.Column(db.Integer, primary_key=True)
    project_id=db.Column(db.String(120), db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    name=db.Column(db.String(255), nullable=False)
    mime_type=db.Column(db.String(150))
    source=db.Column(db.String(120), default='Upload')
    file_data=db.Column(db.LargeBinary, nullable=False)
    size=db.Column(db.Integer, nullable=False)
    created_at=db.Column(db.DateTime, default=datetime.utcnow)

class DailyImport(db.Model):
    __tablename__='daily_imports'
    id=db.Column(db.Integer, primary_key=True)
    import_key=db.Column(db.String(160), unique=True, nullable=False)
    payload=db.Column(db.JSON, nullable=False)
    created_at=db.Column(db.DateTime, default=datetime.utcnow)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'error':'unauthorized'}),401
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

@app.route('/login', methods=['GET','POST'])
def login():
    error=None
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password','')
        expected_email=os.getenv('ADMIN_EMAIL','admin@local').lower()
        password_hash=os.getenv('ADMIN_PASSWORD_HASH')
        password_plain=os.getenv('ADMIN_PASSWORD','changeme')
        ok = check_password_hash(password_hash,password) if password_hash else secrets.compare_digest(password,password_plain)
        if email==expected_email and ok:
            session['authenticated']=True
            session['email']=email
            return redirect(url_for('index'))
        error='E-mail ou senha inválidos.'
    return render_template('login.html',error=error)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')


def seed_if_empty():
    if Project.query.count()>0: return
    seed_path=os.path.join(app.root_path,'data','seed.json')
    with open(seed_path,encoding='utf-8') as f: seed=json.load(f)
    for p in seed.get('projects',[]):
        pr=Project(id=p['id'],name=p['name'],area=p.get('area'),health=p.get('health'),status=p.get('status'),movement=p.get('movement'),owner=p.get('owner'),priority=p.get('priority'),deadline=p.get('deadline'),deadline_label=p.get('deadline_label'),needs_user=p.get('needs_user'),objective=p.get('objective'),done_criteria=p.get('done'),current_state=p.get('current'),next_action=p.get('next'),people=p.get('people',[]))
        db.session.add(pr)
        for i,f in enumerate(p.get('fronts',[])):
            db.session.add(Front(id=f.get('id') or f"{p['id']}-front-{i+1}",project_id=p['id'],name=f.get('name',''),status=f.get('status'),owner=f.get('owner'),next_action=f.get('next'),position=i))
        for i,t in enumerate(p.get('tasks',[])):
            db.session.add(Task(id=t.get('id') or f"{p['id']}-task-{i+1}",project_id=p['id'],title=t.get('title',''),owner=t.get('owner'),due=t.get('due'),priority=t.get('priority'),status=t.get('status'),front=t.get('front')))
        for u in p.get('updates',[]):
            if isinstance(u,list) and len(u)>=4:
                db.session.add(JournalEntry(project_id=p['id'],entry_date=u[0],title=u[1],summary=u[2],next_action=u[3],source='seed'))
    for n in seed.get('notes',[]):
        db.session.add(Note(id=n['id'],title=n.get('title','Sem título'),body=n.get('body'),project=n.get('project'),status=n.get('status'),pinned=bool(n.get('pinned')),created_label=n.get('created')))
    for e in seed.get('agenda',[]):
        db.session.add(AgendaEvent(id=e['id'],date=e.get('date',''),time_label=e.get('time'),title=e.get('title','Sem título'),project=e.get('project'),location=e.get('location'),people=e.get('people'),status=e.get('status'),notes=e.get('notes')))
    db.session.commit()


def project_to_dict(p):
    fronts=Front.query.filter_by(project_id=p.id).order_by(Front.position).all()
    tasks=Task.query.filter_by(project_id=p.id).order_by(Task.created_at).all()
    journal=JournalEntry.query.filter_by(project_id=p.id).order_by(JournalEntry.id.desc()).all()
    attachments=Attachment.query.filter_by(project_id=p.id).order_by(Attachment.id.desc()).all()
    return {
        'id':p.id,'name':p.name,'area':p.area,'health':p.health,'status':p.status,'movement':p.movement,'owner':p.owner,'priority':p.priority,
        'deadline':p.deadline,'deadline_label':p.deadline_label,'needs_user':p.needs_user,'objective':p.objective,'done':p.done_criteria,'current':p.current_state,'next':p.next_action,
        'people':p.people or [],
        'fronts':[{'id':f.id,'name':f.name,'status':f.status,'owner':f.owner,'next':f.next_action} for f in fronts],
        'tasks':[{'id':t.id,'title':t.title,'owner':t.owner,'due':t.due,'priority':t.priority,'status':t.status,'front':t.front} for t in tasks],
        'updates':[[j.entry_date,j.title,j.summary,j.next_action] for j in journal],
        'files':[{'id':a.id,'name':a.name,'type':a.mime_type or 'Arquivo','date':a.created_at.strftime('%d/%m/%Y'),'source':a.source,'real':True,'size':a.size} for a in attachments]
    }

@app.route('/api/state')
@login_required
def api_state():
    return jsonify({
        'version':'3.0',
        'projects':[project_to_dict(p) for p in Project.query.order_by(Project.created_at).all()],
        'notes':[{'id':n.id,'title':n.title,'body':n.body,'project':n.project,'status':n.status,'pinned':n.pinned,'created':n.created_label} for n in Note.query.order_by(Note.pinned.desc(),Note.updated_at.desc()).all()],
        'agenda':[{'id':e.id,'date':e.date,'time':e.time_label,'title':e.title,'project':e.project,'location':e.location,'people':e.people,'status':e.status,'notes':e.notes} for e in AgendaEvent.query.order_by(AgendaEvent.date,AgendaEvent.time_label).all()]
    })

@app.route('/api/notes',methods=['POST'])
@login_required
def save_note():
    d=request.get_json(force=True); nid=d.get('id') or f"note-{int(datetime.utcnow().timestamp()*1000)}"
    n=db.session.get(Note,nid) or Note(id=nid)
    n.title=d.get('title') or 'Sem título'; n.body=d.get('body'); n.project=d.get('project'); n.status=d.get('status'); n.pinned=bool(d.get('pinned')); n.created_label=d.get('created') or datetime.now().strftime('%d/%m/%Y')
    db.session.add(n); db.session.commit(); return jsonify({'ok':True,'id':n.id})

@app.route('/api/agenda',methods=['POST'])
@login_required
def save_event():
    d=request.get_json(force=True); eid=d.get('id') or f"event-{int(datetime.utcnow().timestamp()*1000)}"
    e=db.session.get(AgendaEvent,eid) or AgendaEvent(id=eid)
    e.date=d.get('date') or ''; e.time_label=d.get('time'); e.title=d.get('title') or 'Sem título'; e.project=d.get('project'); e.location=d.get('location'); e.people=d.get('people'); e.status=d.get('status'); e.notes=d.get('notes')
    db.session.add(e); db.session.commit(); return jsonify({'ok':True,'id':e.id})

@app.route('/api/tasks',methods=['POST'])
@login_required
def save_task():
    d=request.get_json(force=True); tid=d.get('id') or f"task-{int(datetime.utcnow().timestamp()*1000)}"
    t=db.session.get(Task,tid) or Task(id=tid,project_id=d['project_id'])
    t.project_id=d['project_id']; t.title=d.get('title') or 'Sem título'; t.owner=d.get('owner'); t.due=d.get('due'); t.priority=d.get('priority'); t.status=d.get('status'); t.front=d.get('front')
    db.session.add(t); db.session.commit(); return jsonify({'ok':True,'id':t.id})

@app.route('/api/tasks/<tid>/toggle',methods=['POST'])
@login_required
def toggle_task(tid):
    t=db.session.get(Task,tid)
    if not t: abort(404)
    t.status='Pendente' if t.status=='Concluído' else 'Concluído'; db.session.commit(); return jsonify({'ok':True,'status':t.status})

@app.route('/api/fronts/<fid>',methods=['POST'])
@login_required
def save_front(fid):
    f=db.session.get(Front,fid)
    if not f: abort(404)
    d=request.get_json(force=True); f.name=d.get('name',f.name); f.status=d.get('status'); f.owner=d.get('owner'); f.next_action=d.get('next')
    db.session.commit(); return jsonify({'ok':True})

@app.route('/api/projects/<pid>',methods=['POST'])
@login_required
def save_project(pid):
    p=db.session.get(Project,pid)
    if not p: abort(404)
    d=request.get_json(force=True)
    mapping={'name':'name','area':'area','health':'health','status':'status','movement':'movement','owner':'owner','priority':'priority','deadline':'deadline','deadline_label':'deadline_label','needs_user':'needs_user','objective':'objective','done':'done_criteria','current':'current_state','next':'next_action'}
    for k,attr in mapping.items():
        if k in d: setattr(p,attr,d[k])
    db.session.commit(); return jsonify({'ok':True})

@app.route('/api/journal/<pid>',methods=['POST'])
@login_required
def add_journal(pid):
    if not db.session.get(Project,pid): abort(404)
    d=request.get_json(force=True)
    j=JournalEntry(project_id=pid,entry_date=d.get('date') or datetime.now().strftime('%d/%m/%Y'),title=d.get('title') or 'Atualização',summary=d.get('summary'),next_action=d.get('next'),source=d.get('source') or 'manual')
    db.session.add(j); db.session.commit(); return jsonify({'ok':True,'id':j.id})

@app.route('/api/files/<pid>',methods=['POST'])
@login_required
def upload_file(pid):
    if not db.session.get(Project,pid): abort(404)
    f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'Arquivo ausente'}),400
    data=f.read()
    a=Attachment(project_id=pid,name=secure_filename(f.filename) or 'arquivo',mime_type=f.mimetype,source='Upload',file_data=data,size=len(data))
    db.session.add(a); db.session.commit(); return jsonify({'ok':True,'id':a.id})

@app.route('/files/<int:file_id>')
@login_required
def download_file(file_id):
    a=db.session.get(Attachment,file_id)
    if not a: abort(404)
    return send_file(BytesIO(a.file_data),mimetype=a.mime_type or 'application/octet-stream',download_name=a.name,as_attachment=False)

@app.route('/api/daily-import',methods=['POST'])
def daily_import():
    token=os.getenv('DAILY_IMPORT_TOKEN')
    if not token or request.headers.get('X-Import-Token')!=token:
        return jsonify({'error':'unauthorized'}),401
    payload=request.get_json(force=True)
    key=payload.get('import_key') or payload.get('date') or str(hash(json.dumps(payload,sort_keys=True)))
    if DailyImport.query.filter_by(import_key=key).first(): return jsonify({'ok':True,'duplicate':True})
    for upd in payload.get('projects',[]):
        p=db.session.get(Project,upd.get('project_id'))
        if not p: continue
        if 'health' in upd: p.health=upd['health']
        if 'status' in upd: p.status=upd['status']
        if 'current' in upd: p.current_state=upd['current']
        if 'next' in upd: p.next_action=upd['next']
        if upd.get('journal'):
            j=upd['journal']; db.session.add(JournalEntry(project_id=p.id,entry_date=j.get('date'),title=j.get('title'),summary=j.get('summary'),next_action=j.get('next'),source='daily_import'))
        for t in upd.get('tasks_create',[]):
            db.session.add(Task(id=t.get('id') or f"task-{int(datetime.utcnow().timestamp()*1000)}-{secrets.token_hex(2)}",project_id=p.id,title=t.get('title','Sem título'),owner=t.get('owner'),due=t.get('due'),priority=t.get('priority'),status=t.get('status','Pendente'),front=t.get('front','Geral')))
    db.session.add(DailyImport(import_key=key,payload=payload)); db.session.commit(); return jsonify({'ok':True})

@app.route('/health')
def health(): return jsonify({'ok':True})

with app.app_context():
    db.create_all(); seed_if_empty()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=os.getenv('FLASK_DEBUG')=='1')
