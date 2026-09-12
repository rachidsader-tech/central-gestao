import gzip, os, secrets, json, hashlib
from datetime import datetime
from flask import render_template, jsonify, request, abort, Response
from sqlalchemy import select, text as sql_text, UniqueConstraint
from werkzeug.security import generate_password_hash

# Carrega o núcleo estável do sistema. A interface V5 usa arquivos HTML/JS normais.
_core_path = os.path.join(os.path.dirname(__file__), 'app_core.py.gz')
with gzip.open(_core_path, 'rt', encoding='utf-8') as _f:
    _source = _f.read()
exec(compile(_source, _core_path, 'exec'), globals(), globals())

# Central unificada V6. Os dados da Transformação KAZ continuam exclusivamente
# em kaz_app_state. Minha Gestão usa tabelas próprias: não há merge, cópia nem
# sincronização automática entre os dois universos.
PERSONAL_VISIBILITIES = ('Privado', 'Delegado', 'Projeto/Compartilhado', 'KAZ')
PERSONAL_STATUSES = ('Não iniciado', 'Em andamento', 'Em risco', 'Concluído', 'Estruturação', 'Em desenvolvimento', 'Conceituação', 'Pré-operação', 'Implantação')

class PersonalProject(db.Model):
    __tablename__ = 'personal_projects'
    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('kaz_users.id'), nullable=False, index=True)
    owner_name = db.Column(db.String(160), nullable=False)
    visibility = db.Column(db.String(40), nullable=False, default='Privado')
    phase = db.Column(db.String(160), default='')
    health = db.Column(db.String(80), default='Normal')
    status = db.Column(db.String(80), default='Não iniciado')
    objective = db.Column(db.Text, default='')
    current_state = db.Column(db.Text, default='')
    last_advance = db.Column(db.Text, default='')
    next_step = db.Column(db.Text, default='')
    priority = db.Column(db.String(80), default='Média')
    deadline = db.Column(db.String(120), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class PersonalMilestone(db.Model):
    __tablename__ = 'personal_milestones'
    id = db.Column(db.String(120), primary_key=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(80), default='Não iniciado')
    responsible_name = db.Column(db.String(160), default='')
    next_step = db.Column(db.Text, default='')
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class PersonalTask(db.Model):
    __tablename__ = 'personal_tasks'
    id = db.Column(db.String(120), primary_key=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=False, index=True)
    milestone_id = db.Column(db.String(120), db.ForeignKey('personal_milestones.id', ondelete='SET NULL'), nullable=True, index=True)
    title = db.Column(db.Text, nullable=False)
    responsible_name = db.Column(db.String(160), default='')
    status = db.Column(db.String(80), default='Pendente')
    priority = db.Column(db.String(80), default='Média')
    due = db.Column(db.String(120), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class PersonalAccess(db.Model):
    __tablename__ = 'personal_access'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('kaz_users.id', ondelete='CASCADE'), nullable=False, index=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=True, index=True)
    milestone_id = db.Column(db.String(120), db.ForeignKey('personal_milestones.id', ondelete='CASCADE'), nullable=True, index=True)
    task_id = db.Column(db.String(120), db.ForeignKey('personal_tasks.id', ondelete='CASCADE'), nullable=True, index=True)
    permission = db.Column(db.String(20), nullable=False, default='edit')
    delegated_by = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('user_id','project_id','milestone_id','task_id', name='uq_personal_access_scope'),)

class PersonalJournal(db.Model):
    __tablename__ = 'personal_journal'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, default='')
    next_step = db.Column(db.Text, default='')
    author = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class PersonalHistory(db.Model):
    __tablename__ = 'personal_history'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=False, index=True)
    author = db.Column(db.String(160), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    detail = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class MigrationBackup(db.Model):
    __tablename__ = 'central_migration_backups'
    id = db.Column(db.Integer, primary_key=True)
    backup_key = db.Column(db.String(120), unique=True, nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    checksum = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

def _personal_seed():
    # Consolidação recuperada da Central de Gestão e dos fechamentos de 10–11/09.
    return [
      {'id':'my-annexo','name':'Annexo','phase':'Pré-operação','health':'Crítico','status':'Em risco','owner':'Rachid','priority':'Alta','deadline':'25/09/2026','objective':'Concluir e colocar em operação o espaço de eventos Annexo, com estrutura completa, padrão definido e primeiro evento viável.','current':'Obra liberada, mas a confirmação de data, obra e cronograma permanece crítica.','last':'10–11/09: sem comprovação física nova; marco de abertura em 25/09 permanece crítico.','next':'Confirmar data, obra e cronograma com Cris, Ricardo e Lucca.','milestones':[('Obra e infraestrutura','Em risco','Cris / Ricardo / Lucca','Fechar cronograma e frentes críticas.'),('Abertura e primeiro evento','Em risco','Rachid / Equipe','Validar prontidão para 25/09.')],'tasks':[('Confirmar cronograma físico e responsáveis','Cris / Ricardo / Lucca','Pendente','Alta','Imediato','Obra e infraestrutura')]},
      {'id':'my-bar','name':'Bar','phase':'Estruturação','health':'Atenção','status':'Estruturação','owner':'Rachid','priority':'Alta','deadline':'','objective':'Estruturar o Bar: conceito, cozinha de apoio, identidade, operação, fornecedores e padrão de serviço.','current':'Responsável principal, cozinha e identidade ainda precisam de definição.','last':'10–11/09: sem nova evidência operacional; foco confirmado nas definições estruturais.','next':'Definir responsável, cozinha e identidade do Bar.','milestones':[('Conceito e identidade','Em andamento','Rachid','Definir proposta e posicionamento.'),('Cozinha e operação','Não iniciado','A definir','Definir modelo operacional.'),('Responsável do projeto','Em risco','Rachid','Indicar responsável principal.')],'tasks':[('Definir responsável principal do Bar','Rachid','Pendente','Alta','Próxima revisão','Responsável do projeto')]},
      {'id':'my-financeiro-contabil','name':'Financeiro / Contábil','phase':'Estruturação','health':'Atenção','status':'Estruturação','owner':'Rachid','priority':'Alta','deadline':'','objective':'Implantar estrutura financeira, contábil, administrativa e gerencial para Bar, Annexo e Galleria.','current':'A prioridade é documentar o primeiro fechamento e consolidar a rotina de controles.','last':'10–11/09: sem nova evidência operacional; primeiro fechamento documentado segue como próximo avanço.','next':'Executar o primeiro fechamento documentado com Vini.','milestones':[('Fluxo financeiro e contábil','Em andamento','Vini','Documentar rotina, aprovações e controles.'),('Primeiro fechamento gerencial','Não iniciado','Vini','Executar e registrar fechamento piloto.')],'tasks':[('Executar primeiro fechamento documentado','Vini','Pendente','Alta','Próxima revisão','Primeiro fechamento gerencial')]},
      {'id':'my-enjoy-albuns','name':'Enjoy / Álbuns','phase':'Desenvolvimento / testes','health':'Atenção','status':'Em desenvolvimento','owner':'Rachid','priority':'Alta','deadline':'','objective':'Implantar fluxo ponta a ponta de produção de álbuns, com automações, responsabilidades por turma e operação validada.','current':'Regras de tratamento e templates foram definidas; falta validar escopo e uma turma piloto.','last':'10–11/09: sem nova evidência operacional; escopo e turma piloto seguem pendentes.','next':'Validar escopo e escolher turma piloto com Kawe e equipe.','milestones':[('Escopo e regras operacionais','Em andamento','Kawe / Equipe','Validar escopo final.'),('Turma piloto','Não iniciado','Kawe / Equipe / Rachid','Selecionar turma e testar fluxo.')],'tasks':[('Validar escopo e turma piloto','Kawe / Equipe / Rachid','Pendente','Alta','Próxima revisão','Turma piloto')]},
      {'id':'my-novo-sistema-vendas','name':'Novo Sistema de Vendas','phase':'Implantação','health':'Atenção','status':'Em andamento','owner':'Rachid','priority':'Alta','deadline':'','objective':'Colocar a operação comercial num fluxo único e registrado, com carteiras, reuniões, orçamento, acompanhamento e responsabilidade clara.','current':'A rotina comercial foi discutida e a operação precisa consolidar a ata e os compromissos de implantação.','last':'10–11/09: reunião comercial de 09/09 registrada; falta consolidar ata e compromissos.','next':'Consolidar ata de 09/09 e compromissos com Ana e coordenadores.','milestones':[('Ata e decisões comerciais','Em andamento','Ana / Coordenadores','Consolidar decisões da reunião de 09/09.'),('Adoção operacional','Em andamento','Ana / Coordenadores','Transformar compromissos em rotina acompanhada.')],'tasks':[('Consolidar ata de 09/09 e compromissos','Ana / Coordenadores','Pendente','Alta','Próxima reunião','Ata e decisões comerciais')]},
      {'id':'my-novo-sistema-entrega-anexxo','name':'Novo Sistema de Entrega / A.NEXXO','phase':'Homologação e ajustes','health':'Atenção','status':'Em desenvolvimento','owner':'Rachid','priority':'Alta','deadline':'','objective':'Colocar em operação o sistema A.NEXXO, estruturando a entrega do evento e validando fluxos, telas, permissões e operação real.','current':'Homologação V34.4 revisada; tela do cliente deve espelhar Preparação. Defeitos confirmados: Cerimonial não chega aos itens a contratar e assumir responsabilidade só funciona na Cozinha.','last':'10/09: homologação prática e briefing de Preparação finalizado; 11/09: manter tela do cliente como Preparação e corrigir os dois defeitos após revisão tela a tela.','next':'Revisar tela a tela, priorizar correções, definir acessos e validar operação real.','milestones':[('Homologação e ajustes','Em andamento','Rachid','Consolidar lista tela a tela.'),('Cliente / Preparação','Em andamento','Rachid','Manter tela do cliente igual à Preparação.'),('Permissões e operação real','Não iniciado','Rachid / Equipe A.NEXXO','Definir acessos e testar ponta a ponta.')],'tasks':[('Corrigir encaminhamento do Cerimonial para itens a contratar','Rachid','Pendente','Alta','Após revisão','Homologação e ajustes'),('Corrigir assumir responsabilidade fora da Cozinha','Rachid','Pendente','Alta','Após revisão','Homologação e ajustes')]},
      {'id':'my-sistema-comissao','name':'Sistema da Comissão','phase':'Conceituação com requisitos ampliados','health':'Atenção','status':'Estruturação','owner':'Rachid','priority':'Alta','deadline':'','objective':'Centralizar informações, solicitações e decisões das comissões, conectando atendimento, projeto e entrega.','current':'Campos obrigatórios, visibilidade e regra de passagem para o assessor ainda precisam ser definidos.','last':'10–11/09: sem nova evidência operacional; confirmação de campos, visibilidade e passagem continua como foco.','next':'Definir campos, visibilidade e passagem com Rachid e Ana.','milestones':[('Campos e informações mínimas','Não iniciado','Rachid / Ana','Definir dados obrigatórios.'),('Visibilidade','Não iniciado','Rachid / Ana','Definir o que cada perfil vê.'),('Passagem para entrega','Não iniciado','Rachid / Ana','Definir passagem para assessor/operação.')],'tasks':[('Definir campos, visibilidade e passagem','Rachid / Ana','Pendente','Alta','Próxima revisão','Campos e informações mínimas')]}
    ]

def _history(project_id, author, action, detail=''):
    db.session.add(PersonalHistory(project_id=project_id, author=author, action=action, detail=detail))

def _create_logical_backup_once():
    if MigrationBackup.query.filter_by(backup_key='pre-central-unificada-v6').first(): return
    # Snapshot lógico dos únicos dados KAZ existentes antes da evolução aditiva.
    state = db.session.get(AppState, 1)
    payload = {
        'kaz_app_state': state.payload if state else None,
        'kaz_revision': state.revision if state else None,
        'kaz_users': [{'id':u.id,'username':u.username,'display_name':u.display_name,'role':u.role,'project_id':u.project_id,'active':u.active} for u in User.query.order_by(User.id).all()],
        'kaz_attachments': [{'id':a.id,'project_id':a.project_id,'milestone_id':a.milestone_id,'name':a.name,'note':a.note,'mime_type':a.mime_type,'size':a.size,'uploaded_by':a.uploaded_by,'created_at':a.created_at.isoformat() if a.created_at else None,'file_data_b64':__import__('base64').b64encode(a.file_data).decode('ascii')} for a in Attachment.query.order_by(Attachment.id).all()]
    }
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    db.session.add(MigrationBackup(backup_key='pre-central-unificada-v6',payload=payload,checksum=hashlib.sha256(raw).hexdigest()))

def _seed_personal_projects_once():
    owner = User.query.filter_by(username='rachid').first()
    if not owner: return
    for item in _personal_seed():
        if db.session.get(PersonalProject,item['id']): continue
        p=PersonalProject(id=item['id'],name=item['name'],owner_user_id=owner.id,owner_name=item['owner'],visibility='Privado',phase=item['phase'],health=item['health'],status=item['status'],objective=item['objective'],current_state=item['current'],last_advance=item['last'],next_step=item['next'],priority=item['priority'],deadline=item['deadline'])
        db.session.add(p)
        for pos,(name,status,responsible,next_step) in enumerate(item['milestones'],1):
            db.session.add(PersonalMilestone(id=f"{item['id']}-m{pos}",project_id=item['id'],name=name,status=status,responsible_name=responsible,next_step=next_step,position=pos))
        for pos,(title,responsible,status,priority,due,milestone_name) in enumerate(item['tasks'],1):
            milestone=next((m for i,m in enumerate(item['milestones'],1) if m[0]==milestone_name),None)
            mid=f"{item['id']}-m{item['milestones'].index(milestone)+1}" if milestone else None
            db.session.add(PersonalTask(id=f"{item['id']}-t{pos}",project_id=item['id'],milestone_id=mid,title=title,responsible_name=responsible,status=status,priority=priority,due=due))
        db.session.flush(); _history(item['id'],'Sistema','Projeto criado em Minha Gestão',item['last'])

def _personal_access(user, project_id, milestone_id=None, task_id=None, permission='view'):
    if not user: return None
    p=db.session.get(PersonalProject,project_id)
    if not p: return None
    if user.id==p.owner_user_id: return 'owner'
    row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=milestone_id,task_id=task_id).first()
    if row: return row.permission
    if milestone_id:
        row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=milestone_id,task_id=None).first()
        if row: return row.permission
    row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=None,task_id=None).first()
    return row.permission if row else None

def _personal_can_edit(user, project_id, milestone_id=None, task_id=None):
    return _personal_access(user,project_id,milestone_id,task_id) in ('owner','edit')

def _personal_visible_projects(user):
    if not user: return []
    owned=PersonalProject.query.filter_by(owner_user_id=user.id).all()
    access=PersonalAccess.query.filter_by(user_id=user.id).all()
    ids={p.id for p in owned}|{a.project_id for a in access if a.project_id}
    return PersonalProject.query.filter(PersonalProject.id.in_(ids)).order_by(PersonalProject.created_at).all() if ids else []

def _personal_serialized(user, project, include_restricted=True):
    accesses=PersonalAccess.query.filter_by(user_id=user.id,project_id=project.id).all()
    owner=user.id==project.owner_user_id
    project_wide=owner or any(a.milestone_id is None and a.task_id is None for a in accesses)
    delegated_milestone_ids={a.milestone_id for a in accesses if a.milestone_id and not a.task_id}
    milestone_ids=set(delegated_milestone_ids)
    task_ids={a.task_id for a in accesses if a.task_id}
    milestones=PersonalMilestone.query.filter_by(project_id=project.id).order_by(PersonalMilestone.position).all()
    tasks=PersonalTask.query.filter_by(project_id=project.id).order_by(PersonalTask.created_at).all()
    if not project_wide:
        allowed_task_milestones={t.milestone_id for t in tasks if t.id in task_ids}
        milestone_ids|={m for m in allowed_task_milestones if m}
        milestones=[m for m in milestones if m.id in milestone_ids]
        # Um acesso a tarefa não abre as outras tarefas do mesmo marco.
        tasks=[t for t in tasks if t.id in task_ids or t.milestone_id in delegated_milestone_ids]
    return {'id':project.id,'name':project.name,'owner':project.owner_name,'visibility':project.visibility,'phase':project.phase,'health':project.health,'status':project.status,'objective':project.objective,'current':project.current_state,'lastAdvance':project.last_advance,'next':project.next_step,'priority':project.priority,'deadline':project.deadline,'restricted':not project_wide,'canEdit':_personal_can_edit(user,project.id),'milestones':[{'id':m.id,'name':m.name,'status':m.status,'owner':m.responsible_name,'next':m.next_step,'canEdit':_personal_can_edit(user,project.id,m.id)} for m in milestones],'tasks':[{'id':t.id,'milestoneId':t.milestone_id,'title':t.title,'owner':t.responsible_name,'status':t.status,'priority':t.priority,'due':t.due,'canEdit':_personal_can_edit(user,project.id,t.milestone_id,t.id)} for t in tasks], 'journal':([] if not project_wide else [{'id':j.id,'title':j.title,'body':j.body,'next':j.next_step,'author':j.author,'at':j.created_at.isoformat()} for j in PersonalJournal.query.filter_by(project_id=project.id).order_by(PersonalJournal.created_at.desc()).all()]), 'history':([] if not project_wide else [{'author':h.author,'action':h.action,'detail':h.detail,'at':h.created_at.isoformat()} for h in PersonalHistory.query.filter_by(project_id=project.id).order_by(PersonalHistory.created_at.desc()).all()])}

# Usuários de consulta: enxergam toda a transformação, mas não possuem projeto e não editam nada.
_VIEWER_USERS = [
    ('julia', 'Julia'),
    ('michele', 'Michele'),
    ('kawe', 'Kawe'),
    ('cole', 'Cole'),
    ('lucas', 'Lucas'),
    ('julio', 'Julio'),
    ('felipe', 'Felipe'),
    ('lais', 'Lais'),
]

def _ensure_viewer_users():
    try:
        with app.app_context():
            with db.engine.begin() as conn:
                for username, display_name in _VIEWER_USERS:
                    # A senha inicial é aleatória e não é exposta nem gravada em texto puro.
                    # O administrador define a senha de entrega em Administração > Usuários.
                    conn.execute(
                        sql_text(
                            """
                            INSERT INTO kaz_users
                                (username, display_name, password_hash, role, project_id, active, created_at)
                            VALUES
                                (:username, :display_name, :password_hash, 'viewer', NULL, TRUE, NOW())
                            ON CONFLICT (username) DO NOTHING
                            """
                        ),
                        {
                            'username': username,
                            'display_name': display_name,
                            'password_hash': generate_password_hash(secrets.token_urlsafe(24)),
                        },
                    )
    except Exception:
        app.logger.exception('Falha ao garantir usuários visualizadores da Transformação KAZ')

_ensure_viewer_users()

@login_required
def _v5_index():
    s = db.session.get(AppState, 1)
    return render_template(
        'index.html',
        initial_state=s.payload,
        revision=s.revision,
        user=public_user(current_user()),
        csrf=session['csrf'],
        directors=DIRECTOR_NAMES
    )
app.view_functions['index'] = _v5_index


def _v5_health():
    return jsonify({'ok': True, 'service': 'transformacao-kaz', 'version': '5.0'})
app.view_functions['health'] = _v5_health


@login_required
def _v5_manual():
    path = os.path.join(app.root_path, 'static', 'Manual_Usuario_Transformacao_KAZ.html')
    if not os.path.exists(path):
        abort(404)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    return Response(
        content,
        mimetype='text/html',
        headers={'Content-Disposition': 'attachment; filename=Manual_Usuario_Transformacao_KAZ.html'}
    )
app.view_functions['manual'] = _v5_manual


@login_required
def _v5_project_action(project_id):
    require_csrf()
    body = request.get_json(force=True)
    action = body.get('action')
    s, p, u = safe_project_write(project_id)
    owner = (u.role == 'owner' and u.project_id == project_id and not is_director(u))

    if action == 'status':
        status = body.get('status')
        if status not in PROJECT_STATUSES:
            return jsonify({'error': 'invalid_status'}), 400
        p['status'] = status

    elif action == 'objective':
        if owner and p.get('validated'):
            return jsonify({'error': 'O objetivo validado só pode ser alterado pela Diretoria.'}), 403
        p['objective'] = (body.get('objective') or '').strip()

    elif action == 'validated':
        if not is_director(u):
            abort(403)
        p['validated'] = bool(body.get('value'))

    elif action == 'general_memo':
        text = (body.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'text_required'}), 400
        p.setdefault('generalMemos', []).append({'at': now_iso(), 'author': u.display_name, 'text': text})
        p['lastUpdate'] = now_iso()

    elif action == 'milestones_finalize':
        if not owner:
            abort(403)
        if p.get('milestonesLocked'):
            return jsonify({'error': 'A estrutura dos marcos já foi finalizada e está bloqueada para o responsável.'}), 400
        updates = body.get('milestones')
        if not isinstance(updates, list) or not updates:
            return jsonify({'error': 'milestones_required'}), 400
        byid = {str(m.get('id')): m for m in p.get('milestones', [])}
        for item in updates:
            m = byid.get(str(item.get('id')))
            if not m:
                continue
            name = (item.get('name') or '').strip()
            if name:
                m['name'] = name
            m['deadline'] = item.get('deadline', '') or ''
            st = item.get('status')
            if st in PROJECT_STATUSES:
                m['status'] = st
            memo = (item.get('memo') or '').strip()
            if memo:
                m.setdefault('memos', []).append({'at': now_iso(), 'author': u.display_name, 'text': memo})
        p['milestonesLocked'] = True
        p['milestonesLockedAt'] = now_iso()
        p['milestonesLockedBy'] = u.display_name
        p['lastUpdate'] = now_iso()
        p.setdefault('history', []).append({
            'at': now_iso(),
            'author': u.display_name,
            'text': 'Estrutura inicial dos marcos finalizada e bloqueada para o responsável.'
        })

    elif action == 'milestone':
        mid = str(body.get('milestoneId'))
        m = next((x for x in p.get('milestones', []) if str(x.get('id')) == mid), None)
        if not m:
            abort(404)

        # Após a revisão inicial do líder, nome e prazo ficam congelados para o responsável.
        # A gestão normal continua: status, memorando e conclusão.
        if not owner or not p.get('milestonesLocked'):
            name = (body.get('name') or '').strip()
            if name:
                m['name'] = name
            if 'deadline' in body and body.get('deadline') is not None:
                m['deadline'] = body.get('deadline', '') or ''

        st = body.get('status')
        if st in PROJECT_STATUSES:
            m['status'] = st
        if 'conclusion' in body:
            m['conclusion'] = body.get('conclusion', '') or ''
        memo = (body.get('memo') or '').strip()
        if memo:
            m.setdefault('memos', []).append({'at': now_iso(), 'author': u.display_name, 'text': memo})

        if m.get('status') == 'Concluído' and not m.get('concludedAt'):
            m['concludedAt'] = now_iso()
        elif m.get('status') != 'Concluído':
            m['concludedAt'] = ''
        p['lastUpdate'] = now_iso()

    elif action == 'unlock_milestones':
        if not is_director(u):
            abort(403)
        p['milestonesLocked'] = False
        p['milestonesLockedAt'] = ''
        p['milestonesLockedBy'] = ''
        p.setdefault('history', []).append({
            'at': now_iso(),
            'author': u.display_name,
            'text': 'Diretoria reabriu excepcionalmente a edição estrutural dos marcos.'
        })

    elif action == 'weekly_commitment':
        # Compromissos não são uma agenda e não são cadastrados soltos no projeto.
        # Eles nascem exclusivamente do fechamento da reunião semanal.
        return jsonify({
            'error': 'Compromissos estratégicos são definidos exclusivamente no fechamento da reunião semanal.'
        }), 403

    elif action == 'commitment_status':
        cid = str(body.get('commitmentId'))
        status = body.get('status')
        if status not in ['Aberto', 'Realizado', 'Parcial', 'Não realizado']:
            return jsonify({'error': 'invalid_status'}), 400
        c = next((x for x in p.get('weeklyCommitments', []) if str(x.get('id')) == cid), None)
        if not c:
            abort(404)
        c['status'] = status
        c['updatedAt'] = now_iso()

    else:
        return jsonify({'error': 'invalid_action'}), 400

    touch_state(s, u)
    return jsonify({'ok': True, 'revision': s.revision})

app.view_functions['project_action'] = _v5_project_action


@login_required
def _v5_create_meeting():
    require_csrf()
    body = request.get_json(force=True)
    u = current_user()
    pid = body.get('projectId', '')
    if not can_edit_project(u, pid):
        abort(403)

    s = db.session.execute(select(AppState).where(AppState.id == 1).with_for_update()).scalar_one()
    p = find_project(s.payload, pid)
    if not p:
        abort(404)

    meeting = {
        'id': secrets.token_hex(7),
        'projectId': pid,
        'at': now_iso(),
        'createdBy': u.display_name,
        'notes': (body.get('notes') or '').strip(),
        'decisions': (body.get('decisions') or '').strip(),
        'nextWeek': (body.get('nextWeek') or '').strip(),
        'transcript': (body.get('transcript') or '').strip(),
        'summary': (body.get('summary') or '').strip(),
        'audioAttachmentId': body.get('audioAttachmentId'),
        'audioUrl': (body.get('audioUrl') or '').strip()
    }
    s.payload.setdefault('meetings', []).append(meeting)
    p['lastUpdate'] = now_iso()

    # O compromisso estratégico nasce do fechamento da reunião, nunca como tarefa solta.
    if meeting['nextWeek']:
        p.setdefault('weeklyCommitments', []).append({
            'id': secrets.token_hex(6),
            'text': meeting['nextWeek'],
            'status': 'Aberto',
            'author': u.display_name,
            'createdAt': now_iso(),
            'source': 'meeting'
        })

    touch_state(s, u)
    return jsonify({'ok': True, 'meeting': meeting, 'revision': s.revision})

app.view_functions['create_meeting'] = _v5_create_meeting

# --- Minha Gestão: API separada e aditiva ---------------------------------
@app.route('/api/minha-gestao/state')
@login_required
def personal_state():
    u=current_user()
    return jsonify({'projects':[_personal_serialized(u,p) for p in _personal_visible_projects(u)],'is_owner':u.username=='rachid'})

def _personal_project_or_404(project_id):
    p=db.session.get(PersonalProject,project_id)
    if not p: abort(404)
    if not _personal_access(current_user(),project_id): abort(403)
    return p

@app.route('/api/minha-gestao/projects/<project_id>', methods=['POST'])
@login_required
def personal_project_action(project_id):
    require_csrf(); body=request.get_json(force=True); u=current_user(); p=_personal_project_or_404(project_id)
    if not _personal_can_edit(u,project_id): abort(403)
    action=body.get('action')
    if action=='update':
        for field,key in [('status','status'),('phase','phase'),('objective','objective'),('current_state','current'),('last_advance','lastAdvance'),('next_step','next'),('priority','priority'),('deadline','deadline'),('visibility','visibility')]:
            if key in body:
                value=(body.get(key) or '').strip()
                if field=='visibility' and value not in PERSONAL_VISIBILITIES: return jsonify({'error':'Visibilidade inválida.'}),400
                setattr(p,field,value)
        _history(project_id,u.display_name,'Projeto atualizado','')
    elif action=='journal':
        title=(body.get('title') or '').strip(); note=(body.get('body') or '').strip()
        if not title or not note: return jsonify({'error':'Título e registro são obrigatórios.'}),400
        db.session.add(PersonalJournal(project_id=project_id,title=title,body=note,next_step=(body.get('next') or '').strip(),author=u.display_name)); _history(project_id,u.display_name,'Diário atualizado',title)
    else: return jsonify({'error':'Ação inválida.'}),400
    db.session.commit(); return jsonify({'ok':True})

@app.route('/api/minha-gestao/milestones/<milestone_id>', methods=['POST'])
@login_required
def personal_milestone_action(milestone_id):
    require_csrf(); body=request.get_json(force=True); u=current_user(); m=db.session.get(PersonalMilestone,milestone_id)
    if not m: abort(404)
    if not _personal_can_edit(u,m.project_id,m.id): abort(403)
    if 'status' in body: m.status=(body.get('status') or '').strip()
    if 'next' in body: m.next_step=(body.get('next') or '').strip()
    if 'owner' in body: m.responsible_name=(body.get('owner') or '').strip()
    _history(m.project_id,u.display_name,'Marco atualizado',m.name); db.session.commit(); return jsonify({'ok':True})

@app.route('/api/minha-gestao/tasks/<task_id>', methods=['POST'])
@login_required
def personal_task_action(task_id):
    require_csrf(); body=request.get_json(force=True); u=current_user(); t=db.session.get(PersonalTask,task_id)
    if not t: abort(404)
    if not _personal_can_edit(u,t.project_id,t.milestone_id,t.id): abort(403)
    if 'status' in body: t.status=(body.get('status') or '').strip()
    if 'owner' in body: t.responsible_name=(body.get('owner') or '').strip()
    if 'due' in body: t.due=(body.get('due') or '').strip()
    _history(t.project_id,u.display_name,'Pendência atualizada',t.title); db.session.commit(); return jsonify({'ok':True})

@app.route('/api/minha-gestao/delegate', methods=['POST'])
@login_required
def personal_delegate():
    require_csrf(); body=request.get_json(force=True); u=current_user(); level=body.get('level'); target_id=(body.get('targetId') or '').strip(); username=(body.get('username') or '').strip().lower(); permission=(body.get('permission') or 'edit').strip()
    if level not in ('project','milestone','task') or permission not in ('view','edit'): return jsonify({'error':'Delegação inválida.'}),400
    target=None; project_id=None; milestone_id=None; task_id=None
    if level=='project': target=db.session.get(PersonalProject,target_id); project_id=target_id if target else None
    elif level=='milestone': target=db.session.get(PersonalMilestone,target_id); project_id=target.project_id if target else None; milestone_id=target_id
    else: target=db.session.get(PersonalTask,target_id); project_id=target.project_id if target else None; milestone_id=target.milestone_id if target else None; task_id=target_id
    if not target: abort(404)
    p=db.session.get(PersonalProject,project_id)
    if u.id!=p.owner_user_id: abort(403)
    recipient=User.query.filter_by(username=username,active=True).first()
    if not recipient: return jsonify({'error':'Usuário ativo não encontrado.'}),400
    row=PersonalAccess.query.filter_by(user_id=recipient.id,project_id=project_id,milestone_id=milestone_id,task_id=task_id).first()
    if row: row.permission=permission; row.delegated_by=u.display_name
    else: db.session.add(PersonalAccess(user_id=recipient.id,project_id=project_id,milestone_id=milestone_id,task_id=task_id,permission=permission,delegated_by=u.display_name))
    if p.visibility=='Privado': p.visibility='Delegado'
    label={'project':'Projeto','milestone':'Marco','task':'Pendência'}[level]
    _history(project_id,u.display_name,f'{label} delegado',f'{recipient.display_name} · {permission}')
    db.session.commit(); return jsonify({'ok':True,'recipient':public_user(recipient)})

@app.route('/api/minha-gestao/users')
@login_required
def personal_users():
    u=current_user()
    if u.username!='rachid': abort(403)
    return jsonify([public_user(x) for x in User.query.filter_by(active=True).order_by(User.display_name).all()])

def _initialize_unified_central():
    with app.app_context():
        # Apenas CREATE TABLE; nenhuma tabela ou linha KAZ é alterada.
        db.create_all()
        _create_logical_backup_once()
        _seed_personal_projects_once()
        db.session.commit()

_initialize_unified_central()
