import os, json, secrets
from datetime import datetime
from functools import wraps
from io import BytesIO
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app=Flask(__name__)
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32),MAX_CONTENT_LENGTH=12*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('RENDER','').lower()=='true')
db_url=os.getenv('DATABASE_URL','sqlite:///transformacao_kaz.db')
if db_url.startswith('postgres://'): db_url=db_url.replace('postgres://','postgresql://',1)
if db_url.startswith('postgresql://'): db_url=db_url.replace('postgresql://','postgresql+psycopg://',1)
app.config['SQLALCHEMY_DATABASE_URI']=db_url; app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
db=SQLAlchemy(app)
PROJECT_STATUSES=['Não iniciado','Em andamento','Em risco','Concluído']
DEPENDENCY_STATUSES=['Aberta','Em análise','Respondida','Resolvida']
DIRECTOR_NAMES=['Rachid','Leo','Márcio','Marcinho']
DIRECTOR_USERNAMES=['rachid','leo','marcio','marcinho']

class User(db.Model):
    __tablename__='kaz_users'; id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(80),unique=True,nullable=False); display_name=db.Column(db.String(160),nullable=False); password_hash=db.Column(db.String(255),nullable=False); role=db.Column(db.String(30),nullable=False,default='owner'); project_id=db.Column(db.String(80)); active=db.Column(db.Boolean,nullable=False,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class AppState(db.Model):
    __tablename__='kaz_app_state'; id=db.Column(db.Integer,primary_key=True,default=1); payload=db.Column(db.JSON,nullable=False); revision=db.Column(db.Integer,nullable=False,default=1); updated_by=db.Column(db.String(160)); updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
class Attachment(db.Model):
    __tablename__='kaz_attachments'; id=db.Column(db.Integer,primary_key=True); project_id=db.Column(db.String(80),nullable=False,index=True); milestone_id=db.Column(db.String(120),index=True); name=db.Column(db.String(255),nullable=False); note=db.Column(db.String(500)); mime_type=db.Column(db.String(180)); size=db.Column(db.Integer,nullable=False); file_data=db.Column(db.LargeBinary,nullable=False); uploaded_by=db.Column(db.String(160)); created_at=db.Column(db.DateTime,default=datetime.utcnow)
OWNER_SEEDS=[('ana','Ana Silvia','owner','comercial'),('oscar','Oscar','owner','projetos'),('raquel','Raquel','owner','posvenda'),('ju','Ju Hirota','owner','producao'),('wancler','Wancler','owner','compras'),('erik','Erik','owner','financeiro'),('vini','Vini','owner','planejamento'),('marcio','Márcio','direction',None),('marcinho','Marcinho','direction',None),('leo','Leo','direction',None)]

def now_iso(): return datetime.utcnow().replace(microsecond=0).isoformat()+'Z'
def load_seed():
    with open(os.path.join(app.root_path,'seed_state.json'),encoding='utf-8') as f: return json.load(f)
def normalize_state(payload):
    changed=False
    if not isinstance(payload,dict): payload=load_seed(); changed=True
    else: payload=json.loads(json.dumps(payload,ensure_ascii=False))
    version=int(payload.get('schemaVersion') or 1); payload.setdefault('dependencies',[]); payload.setdefault('meetings',[]); payload['direction']=DIRECTOR_NAMES
    for p in payload.get('projects',[]):
        if p.get('status') not in PROJECT_STATUSES: p['status']='Não iniciado'; changed=True
        for k in ['generalMemos','files','weeklyCommitments','history']:
            if k not in p: p[k]=[]; changed=True
        p.setdefault('lastUpdate',''); p.setdefault('validated',False)
        for m in p.get('milestones',[]):
            if m.get('status') not in PROJECT_STATUSES: m['status']='Não iniciado'; changed=True
            m.setdefault('memos',[]); m.setdefault('files',[]); m.setdefault('deadline',''); m.setdefault('conclusion',''); m.setdefault('concludedAt','')
    if version<2:
        for p in payload.get('projects',[]):
            if p.get('id')=='comercial': p['validated']=False; p['status']='Não iniciado'
        for d in payload.get('dependencies',[]):
            d.setdefault('history',[]); d.setdefault('responses',[]); d.setdefault('comments',[]); d.setdefault('status','Aberta'); d.setdefault('director','')
        payload['schemaVersion']=2; changed=True
    return payload,changed
def seed_if_empty():
    state=db.session.get(AppState,1)
    if not state: db.session.add(AppState(id=1,payload=load_seed(),revision=1,updated_by='Sistema'))
    else:
        normalized,changed=normalize_state(state.payload)
        if changed: state.payload=normalized; flag_modified(state,'payload'); state.revision+=1; state.updated_by='Migração V2'; state.updated_at=datetime.utcnow()
    admin_username=os.getenv('ADMIN_USERNAME','rachid').strip().lower(); admin_password=os.getenv('ADMIN_PASSWORD') or 'change-me-now'; admin=User.query.filter_by(username=admin_username).first()
    if not admin: db.session.add(User(username=admin_username,display_name='Rachid',password_hash=generate_password_hash(admin_password),role='admin',active=True))
    for username,name,role,pid in OWNER_SEEDS:
        u=User.query.filter_by(username=username).first()
        if not u: db.session.add(User(username=username,display_name=name,password_hash=generate_password_hash(secrets.token_urlsafe(32)),role=role,project_id=pid,active=False))
        else: u.display_name=name; u.role=role; u.project_id=pid
    db.session.commit()
def current_user():
    uid=session.get('user_id'); return db.session.get(User,uid) if uid else None
def login_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        u=current_user()
        if not u or not u.active:
            session.clear()
            if request.path.startswith('/api/'): return jsonify({'error':'unauthorized'}),401
            return redirect(url_for('login'))
        return fn(*a,**kw)
    return wrapped
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*a,**kw):
        if current_user().role!='admin': abort(403)
        return fn(*a,**kw)
    return wrapped
def require_csrf():
    token=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token or not secrets.compare_digest(token,session.get('csrf','')): abort(403)
def is_director(u): return bool(u and (u.role in ('admin','direction') or u.username in DIRECTOR_USERNAMES))
def public_user(u): return {'id':u.id,'username':u.username,'display_name':u.display_name,'role':u.role,'project_id':u.project_id,'active':u.active,'is_director':is_director(u)}
def can_edit_project(u,pid): return bool(u and (is_director(u) or (u.role=='owner' and u.project_id==pid)))
def canonical(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def find_project(payload,pid): return next((p for p in payload.get('projects',[]) if p.get('id')==pid),None)
def find_dependency(payload,did): return next((d for d in payload.get('dependencies',[]) if str(d.get('id'))==str(did)),None)
def append_history(dep,action,actor,detail=''):
    dep.setdefault('history',[]).append({'at':now_iso(),'actor':actor.display_name,'action':action,'detail':detail}); dep['updatedAt']=now_iso()
def validate_dependencies(deps):
    if not isinstance(deps,list): abort(400)
    for d in deps:
        if d.get('status') not in DEPENDENCY_STATUSES or d.get('director') not in DIRECTOR_NAMES or not d.get('projectId'): abort(400)
def enforce_state_change(old,new,u):
    if is_director(u): validate_dependencies(new.get('dependencies',[])); return
    if u.role!='owner' or not u.project_id: abort(403)
    op={p.get('id'):p for p in old.get('projects',[])}; np={p.get('id'):p for p in new.get('projects',[])}
    if set(op)!=set(np): abort(403)
    for pid,p in op.items():
        if pid!=u.project_id and canonical(p)!=canonical(np[pid]): abort(403)
        if pid==u.project_id and p.get('validated')!=np[pid].get('validated'): abort(403)
    if canonical(old.get('dependencies',[]))!=canonical(new.get('dependencies',[])): abort(403)
    om={str(m.get('id')):m for m in old.get('meetings',[])}
    for m in new.get('meetings',[]):
        mid=str(m.get('id'))
        if m.get('projectId')!=u.project_id and (mid not in om or canonical(m)!=canonical(om[mid])): abort(403)
    ni={str(m.get('id')) for m in new.get('meetings',[])}
    if any(mid not in ni and om[mid].get('projectId')!=u.project_id for mid in om): abort(403)

@app.route('/health')
def health(): return jsonify({'ok':True,'service':'transformacao-kaz','version':'2.0'})
@app.route('/login',methods=['GET','POST'])
def login():
    if current_user() and current_user().active: return redirect(url_for('index'))
    error=None
    if request.method=='POST':
        u=User.query.filter_by(username=request.form.get('username','').strip().lower()).first(); password=request.form.get('password','')
        if u and u.active and check_password_hash(u.password_hash,password): session.clear(); session['user_id']=u.id; session['csrf']=secrets.token_urlsafe(24); return redirect(url_for('index'))
        error='Usuário ou senha inválidos.'
    return render_template('login.html',error=error)
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/')
@login_required
def index():
    s=db.session.get(AppState,1); return render_template('index.html',initial_state=s.payload,revision=s.revision,user=public_user(current_user()),csrf=session['csrf'],project_statuses=PROJECT_STATUSES,dependency_statuses=DEPENDENCY_STATUSES,directors=DIRECTOR_NAMES)
@app.route('/api/state')
@login_required
def api_get_state():
    s=db.session.get(AppState,1); return jsonify({'state':s.payload,'revision':s.revision,'updated_by':s.updated_by,'updated_at':s.updated_at.isoformat() if s.updated_at else None})
@app.route('/api/state',methods=['POST'])
@login_required
def api_save_state():
    require_csrf(); body=request.get_json(force=True); payload=body.get('state')
    try: rev=int(body.get('revision',0))
    except: return jsonify({'error':'invalid_revision'}),400
    if not isinstance(payload,dict) or not isinstance(payload.get('projects'),list): return jsonify({'error':'invalid_state'}),400
    s=db.session.execute(select(AppState).where(AppState.id==1).with_for_update()).scalar_one()
    if rev!=s.revision: return jsonify({'error':'conflict','revision':s.revision,'state':s.payload}),409
    enforce_state_change(s.payload,payload,current_user()); payload['schemaVersion']=2; s.payload=payload; flag_modified(s,'payload'); s.revision+=1; s.updated_by=current_user().display_name; s.updated_at=datetime.utcnow(); db.session.commit(); return jsonify({'ok':True,'revision':s.revision})
@app.route('/api/dependencies',methods=['POST'])
@login_required
def create_dependency():
    require_csrf(); body=request.get_json(force=True); u=current_user(); pid=body.get('projectId','')
    if not can_edit_project(u,pid): abort(403)
    director=(body.get('director') or '').strip(); subject=(body.get('subject') or '').strip(); description=(body.get('description') or '').strip()
    if director not in DIRECTOR_NAMES or not subject: return jsonify({'error':'invalid_dependency'}),400
    s=db.session.execute(select(AppState).where(AppState.id==1).with_for_update()).scalar_one()
    if not find_project(s.payload,pid): abort(404)
    dep={'id':secrets.token_hex(8),'projectId':pid,'requester':u.display_name,'createdBy':u.username,'subject':subject,'description':description,'director':director,'deadline':body.get('deadline',''),'status':'Aberta','createdAt':now_iso(),'updatedAt':now_iso(),'responses':[],'comments':[],'history':[],'resolution':''}
    append_history(dep,'Pendência aberta',u,f'Diretor responsável: {director}'); s.payload.setdefault('dependencies',[]).append(dep); flag_modified(s,'payload'); s.revision+=1; s.updated_by=u.display_name; s.updated_at=datetime.utcnow(); db.session.commit(); return jsonify({'ok':True,'dependency':dep,'revision':s.revision})
@app.route('/api/dependencies/<dep_id>/action',methods=['POST'])
@login_required
def dependency_action(dep_id):
    require_csrf(); u=current_user(); body=request.get_json(force=True); action=body.get('action'); s=db.session.execute(select(AppState).where(AppState.id==1).with_for_update()).scalar_one(); dep=find_dependency(s.payload,dep_id)
    if not dep: abort(404)
    own=u.role=='owner' and u.project_id==dep.get('projectId'); director=is_director(u); text=(body.get('text') or '').strip()
    if action=='assume':
        if not director or u.display_name!=dep.get('director'): abort(403)
        if dep.get('status')=='Resolvida': return jsonify({'error':'resolved'}),400
        dep['status']='Em análise'; append_history(dep,'Pendência assumida',u)
    elif action=='respond':
        if not director: abort(403)
        if not text: return jsonify({'error':'text_required'}),400
        dep.setdefault('responses',[]).append({'at':now_iso(),'actor':u.display_name,'text':text}); dep['status']='Respondida'; append_history(dep,'Resposta da Diretoria',u,text)
    elif action=='comment':
        if not (director or own): abort(403)
        if not text: return jsonify({'error':'text_required'}),400
        dep.setdefault('comments',[]).append({'at':now_iso(),'actor':u.display_name,'text':text}); append_history(dep,'Informação adicionada',u,text)
    elif action=='resolve':
        if not (director or own): abort(403)
        dep['status']='Resolvida'; dep['resolution']=text; append_history(dep,'Pendência resolvida',u,text or 'Encerrada')
    elif action=='reopen':
        if not (director or own): abort(403)
        if dep.get('status')!='Resolvida': return jsonify({'error':'not_resolved'}),400
        if not text: return jsonify({'error':'reason_required'}),400
        dep['status']='Em análise'; append_history(dep,'Pendência reaberta',u,text)
    elif action=='change_director':
        if not director: abort(403)
        nd=(body.get('director') or '').strip()
        if nd not in DIRECTOR_NAMES: return jsonify({'error':'invalid_director'}),400
        old=dep.get('director'); dep['director']=nd; append_history(dep,'Diretor responsável alterado',u,f'{old} → {nd}')
    elif action=='change_deadline':
        if not (director or own): abort(403)
        old=dep.get('deadline',''); dep['deadline']=body.get('deadline',''); append_history(dep,'Prazo alterado',u,f'{old or "sem prazo"} → {dep["deadline"] or "sem prazo"}')
    else: return jsonify({'error':'invalid_action'}),400
    flag_modified(s,'payload'); s.revision+=1; s.updated_by=u.display_name; s.updated_at=datetime.utcnow(); db.session.commit(); return jsonify({'ok':True,'dependency':dep,'revision':s.revision})
@app.route('/api/attachments',methods=['POST'])
@login_required
def upload_attachment():
    require_csrf(); f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'missing_file'}),400
    data=f.read()
    if len(data)>12*1024*1024: return jsonify({'error':'too_large'}),413
    pid=request.form.get('project_id',''); u=current_user()
    if not can_edit_project(u,pid): abort(403)
    a=Attachment(project_id=pid,milestone_id=request.form.get('milestone_id') or None,name=secure_filename(f.filename) or 'arquivo',note=request.form.get('note','').strip(),mime_type=f.mimetype,size=len(data),file_data=data,uploaded_by=u.display_name); db.session.add(a); db.session.commit(); return jsonify({'id':a.id,'name':a.name,'size':a.size,'note':a.note,'date':a.created_at.strftime('%d/%m/%Y %H:%M'),'url':url_for('download_attachment',attachment_id=a.id)})
@app.route('/attachments/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    a=db.session.get(Attachment,attachment_id)
    if not a: abort(404)
    return send_file(BytesIO(a.file_data),mimetype=a.mime_type or 'application/octet-stream',as_attachment=True,download_name=a.name)
@app.route('/api/users')
@login_required
def api_users(): return jsonify([public_user(u) for u in User.query.order_by(User.display_name).all()])
@app.route('/admin/users',methods=['GET','POST'])
@admin_required
def admin_users():
    message=error=None
    if request.method=='POST':
        require_csrf(); u=db.session.get(User,int(request.form['user_id']))
        if not u: abort(404)
        u.display_name=request.form.get('display_name',u.display_name).strip() or u.display_name; u.active=request.form.get('active')=='on'; password=request.form.get('password','')
        if password:
            if len(password)<8: error='A senha precisa ter pelo menos 8 caracteres.'
            else: u.password_hash=generate_password_hash(password)
        if not error: db.session.commit(); message=f'Usuário {u.display_name} atualizado.'
    users=User.query.order_by(User.display_name).all(); state=db.session.get(AppState,1).payload; projects=[(p['id'],p['name']) for p in state.get('projects',[])]; return render_template('users.html',users=users,projects=projects,csrf=session['csrf'],message=message,error=error)

with app.app_context(): db.create_all(); seed_if_empty()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=os.getenv('FLASK_DEBUG')=='1')
