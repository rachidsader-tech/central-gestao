import gzip, os, secrets, json, hashlib
from datetime import datetime
from flask import render_template, jsonify, request, abort, Response
from sqlalchemy import inspect, select, text as sql_text, UniqueConstraint
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
    # owner_* identifica quem criou e administra o projeto. O responsável pode
    # ser alterado sem retirar o acesso do proprietário original.
    responsible_user_id = db.Column(db.Integer, nullable=True, index=True)
    responsible_name = db.Column(db.String(160), default='')
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
    category = db.Column(db.String(120), default='')
    status = db.Column(db.String(80), default='Não iniciado')
    health = db.Column(db.String(80), default='')
    responsible_user_id = db.Column(db.Integer, nullable=True, index=True)
    responsible_name = db.Column(db.String(160), default='')
    next_step = db.Column(db.Text, default='')
    deadline = db.Column(db.String(120), default='')
    notes = db.Column(db.Text, default='')
    conclusion = db.Column(db.Text, default='')
    concluded_at = db.Column(db.DateTime, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
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

class PersonalMilestoneRecord(db.Model):
    __tablename__ = 'personal_milestone_records'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(100), db.ForeignKey('personal_projects.id', ondelete='CASCADE'), nullable=False, index=True)
    milestone_id = db.Column(db.String(120), db.ForeignKey('personal_milestones.id', ondelete='CASCADE'), nullable=False, index=True)
    author = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
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

PERSONAL_PROJECT_NAMES = {
    'my-annexo': 'Annexo',
    'my-bar': 'Bar',
    'my-financeiro-contabil': 'Financeiro / Contábil',
    'my-enjoy-albuns': 'Enjoy / Álbuns',
    'my-novo-sistema-vendas': 'Sistema de Vendas',
    'my-novo-sistema-entrega-anexxo': 'Sistema de Entrega',
    'my-sistema-comissao': 'Sistema da Comissão',
}

def _ensure_personal_v8_schema():
    """Migração aditiva restrita às tabelas personal_*.

    db.create_all não adiciona colunas em tabelas existentes. Esta função
    acrescenta apenas os campos necessários para responsabilidade e para a
    estrutura completa dos marcos; kaz_app_state e as tabelas KAZ não entram
    nesta migração.
    """
    additions = {
        'personal_projects': {
            'responsible_user_id': 'INTEGER',
            'responsible_name': "VARCHAR(160) DEFAULT ''",
        },
        'personal_milestones': {
            'category': "VARCHAR(120) DEFAULT ''",
            'health': "VARCHAR(80) DEFAULT ''",
            'responsible_user_id': 'INTEGER',
            'deadline': "VARCHAR(120) DEFAULT ''",
            'notes': "TEXT DEFAULT ''",
            'conclusion': "TEXT DEFAULT ''",
            'concluded_at': 'TIMESTAMP',
            'active': 'BOOLEAN NOT NULL DEFAULT TRUE',
        },
    }
    db_inspector = inspect(db.engine)
    with db.engine.begin() as conn:
        for table_name, columns in additions.items():
            existing = {column['name'] for column in db_inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    conn.execute(sql_text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}'))
        conn.execute(sql_text('CREATE INDEX IF NOT EXISTS ix_personal_projects_responsible_user_id ON personal_projects (responsible_user_id)'))
        conn.execute(sql_text('CREATE INDEX IF NOT EXISTS ix_personal_milestones_responsible_user_id ON personal_milestones (responsible_user_id)'))
        conn.execute(sql_text('CREATE INDEX IF NOT EXISTS ix_personal_milestones_active ON personal_milestones (active)'))

def _create_personal_v8_backup_once():
    if MigrationBackup.query.filter_by(backup_key='personal-before-v8-89-marcos').first():
        return
    project_ids = tuple(PERSONAL_PROJECT_NAMES)
    payload = {
        'projects': [{column.name:getattr(row,column.name) for column in PersonalProject.__table__.columns if column.name not in ('created_at','updated_at')} for row in PersonalProject.query.filter(PersonalProject.id.in_(project_ids)).all()],
        'milestones': [{column.name:getattr(row,column.name) for column in PersonalMilestone.__table__.columns if column.name!='created_at'} for row in PersonalMilestone.query.filter(PersonalMilestone.project_id.in_(project_ids)).all()],
        'tasks': [{column.name:getattr(row,column.name) for column in PersonalTask.__table__.columns if column.name not in ('created_at','updated_at')} for row in PersonalTask.query.filter(PersonalTask.project_id.in_(project_ids)).all()],
        'access': [{column.name:getattr(row,column.name) for column in PersonalAccess.__table__.columns if column.name!='created_at'} for row in PersonalAccess.query.filter(PersonalAccess.project_id.in_(project_ids)).all()],
    }
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    db.session.add(MigrationBackup(backup_key='personal-before-v8-89-marcos',payload=payload,checksum=hashlib.sha256(raw).hexdigest()))

def _restore_personal_milestones_v8_once():
    """Restaura as 89 etapas históricas como marcos ativos dos 7 projetos.

    Os marcos-resumo da V7 não são apagados: ficam inativos e permanecem no
    banco com seus vínculos. Nenhum projeto, usuário ou registro KAZ é lido ou
    alterado por esta rotina.
    """
    marker = '89 etapas históricas restauradas sem excluir a V7'
    if PersonalHistory.query.filter_by(action='Restauração estrutural V8', detail=marker).first():
        return
    path = os.path.join(os.path.dirname(__file__), 'personal_milestones_v8.json')
    with open(path, encoding='utf-8') as source:
        data = json.load(source)
    projects = data.get('projects') or {}
    if set(projects) != set(PERSONAL_PROJECT_NAMES):
        raise RuntimeError('A restauração V8 não contém exatamente os 7 projetos pessoais.')
    if sum(len(items) for items in projects.values()) != 89:
        raise RuntimeError('A restauração V8 precisa conter exatamente 89 marcos.')

    for project_id, items in projects.items():
        project = db.session.get(PersonalProject, project_id)
        if not project:
            continue
        project.name = PERSONAL_PROJECT_NAMES[project_id]
        # Apenas os marcos-resumo conhecidos da V7 são desativados. Nenhuma
        # linha é excluída e um eventual marco novo permanece intacto.
        PersonalMilestone.query.filter(
            PersonalMilestone.project_id == project_id,
            PersonalMilestone.id.like(f'{project_id}-m%'),
        ).update({'active': False}, synchronize_session=False)
        for position, item in enumerate(items, 1):
            milestone = db.session.get(PersonalMilestone, item['id'])
            if not milestone:
                milestone = PersonalMilestone(id=item['id'], project_id=project_id)
                db.session.add(milestone)
            milestone.name = item['name']
            milestone.category = item['category']
            milestone.status = item['status']
            milestone.health = item['health']
            legacy_responsible = (item.get('responsible') or '').strip()
            # "A definir" significa ausência de responsável próprio; nesse
            # caso o marco herda automaticamente o responsável do projeto.
            milestone.responsible_name = '' if legacy_responsible.casefold() == 'a definir' else legacy_responsible
            milestone.next_step = item['next']
            milestone.deadline = item['deadline']
            milestone.notes = item['notes']
            milestone.position = position
            milestone.active = True
        _history(project_id, 'Sistema', 'Restauração estrutural V8', marker)

def _seed_personal_projects_once():
    owner = User.query.filter_by(username='rachid').first()
    if not owner: return
    for item in _personal_seed():
        if db.session.get(PersonalProject,item['id']): continue
        p=PersonalProject(id=item['id'],name=item['name'],owner_user_id=owner.id,owner_name=item['owner'],visibility='Privado',phase=item['phase'],health=item['health'],status=item['status'],objective=item['objective'],current_state=item['current'],last_advance=item['last'],next_step=item['next'],priority=item['priority'],deadline=item['deadline'])
        db.session.add(p)
        # A FK dos marcos exige que o projeto pai exista antes dos filhos.
        db.session.flush()
        for pos,(name,status,responsible,next_step) in enumerate(item['milestones'],1):
            db.session.add(PersonalMilestone(id=f"{item['id']}-m{pos}",project_id=item['id'],name=name,status=status,responsible_name=responsible,next_step=next_step,position=pos))
        for pos,(title,responsible,status,priority,due,milestone_name) in enumerate(item['tasks'],1):
            milestone=next((m for i,m in enumerate(item['milestones'],1) if m[0]==milestone_name),None)
            mid=f"{item['id']}-m{item['milestones'].index(milestone)+1}" if milestone else None
            db.session.add(PersonalTask(id=f"{item['id']}-t{pos}",project_id=item['id'],milestone_id=mid,title=title,responsible_name=responsible,status=status,priority=priority,due=due))
        db.session.flush(); _history(item['id'],'Sistema','Projeto criado em Minha Gestão',item['last'])

def _reconstruct_personal_content_v7_once():
    """Atualiza somente o conteúdo dos 7 projetos de Minha Gestão.
    Não altera registros KAZ, donos, visibilidade, permissões ou estrutura.
    """
    if PersonalHistory.query.filter_by(action='Reconstrução de conteúdo V7', detail='CENTRAL DE GESTÃO - PROJETOS').first():
        return
    projects = {
      'my-annexo': {
        'phase':'Pré-operação', 'health':'Crítico', 'status':'Em risco',
        'objective':'Concluir a obra e colocar o Annexo em operação, com estrutura, cronograma, evidências e primeiros eventos viáveis.',
        'current_state':'Obra e abertura seguem críticas, sem atualização física confirmada.',
        'last_advance':'Reconstrução consolidada: obra, cronograma, evidências e eventos de 24/09, 25/09 e 27/09.',
        'next_step':'Confirmar o marco de 25/09, a execução física e o cronograma com Cris, Ricardo e Lucca.',
        'deadline':'25/09/2026',
        'milestones':[('m1','Obra e infraestrutura','Em risco','Cris / Ricardo / Lucca','Concluir frentes físicas críticas.'),('m2','Eventos de 24/09, 25/09 e 27/09','Em risco','Rachid / Cris / Ricardo','Confirmar prontidão de cada evento.'),('m3','Cronograma e evidências','Em risco','Cris / Ricardo / Lucca','Consolidar cronograma e evidências atualizadas.')],
        'tasks':[('t1','Confirmar marco de 25/09, execução física e cronograma','Cris / Ricardo / Lucca','Pendente','Alta','Imediato','m3'),('t2','Consolidar evidências das frentes críticas','Cris / Ricardo / Lucca','Pendente','Alta','Imediato','m3')]
      },
      'my-bar': {
        'phase':'Estruturação', 'health':'Atenção', 'status':'Estruturação',
        'objective':'Estruturar o Bar com mobiliário, cozinha, layout e identidade, cardápio, custos e uma operação-teste.',
        'current_state':'Sem atualização operacional confirmada; responsável, cozinha e identidade seguem em definição.',
        'last_advance':'Reconstrução das frentes de mobiliário, cozinha, layout/identidade, cardápio, custos e operação-teste.',
        'next_step':'Definir responsável principal, cozinha e identidade do Bar.',
        'milestones':[('m1','Mobiliário','Não iniciado','A definir','Definir necessidades e padrão.'),('m2','Cozinha','Não iniciado','A definir','Definir modelo e infraestrutura de apoio.'),('m3','Layout / identidade','Em andamento','Rachid','Definir conceito e identidade.'),('m4','Cardápio','Não iniciado','A definir','Definir proposta inicial.'),('m5','Custos','Não iniciado','A definir','Consolidar custos e premissas.'),('m6','Operação-teste','Não iniciado','Rachid / A definir','Planejar teste operacional.')],
        'tasks':[('t1','Definir responsável principal, cozinha e identidade','Rachid / A definir','Pendente','Alta','Próxima revisão','m3')]
      },
      'my-financeiro-contabil': {
        'phase':'Estruturação', 'health':'Atenção', 'status':'Estruturação',
        'objective':'Organizar a estrutura financeira e contábil, com pagamentos associados, fluxo documentado e fechamento gerencial recorrente.',
        'current_state':'Pagamentos associados e fluxo parcialmente reconstruído; primeiro fechamento ainda não executado.',
        'last_advance':'Fluxo financeiro parcialmente reconstruído e pagamentos associados mapeados.',
        'next_step':'Executar o primeiro fechamento documentado.',
        'milestones':[('m1','Fluxo financeiro e contábil','Em andamento','Vini / A definir','Documentar fluxo e responsabilidades.'),('m2','Pagamentos associados','Em andamento','Vini','Consolidar associação e controles.'),('m3','Primeiro fechamento documentado','Não iniciado','Vini / A definir','Executar fechamento piloto e registrar resultado.')],
        'tasks':[('t1','Executar o primeiro fechamento documentado','Vini / A definir','Pendente','Alta','Próxima revisão','m3')]
      },
      'my-enjoy-albuns': {
        'phase':'Desenvolvimento / testes', 'health':'Atenção', 'status':'Em desenvolvimento',
        'objective':'Validar o Controle de Diagramação e o fluxo de produção de álbuns com painel visual, operação e turma piloto.',
        'current_state':'Escopo V1 do Controle de Diagramação e painel visual produzidos; validação operacional pendente.',
        'last_advance':'Escopo V1 e painel visual produzidos; sem atualização operacional posterior confirmada.',
        'next_step':'Validar com a operação e escolher uma turma piloto.',
        'milestones':[('m1','Controle de Diagramação — Escopo V1','Em andamento','Kawe / Equipe / Rachid','Validar escopo com operação.'),('m2','Painel visual','Em andamento','Kawe / Equipe','Validar uso operacional.'),('m3','Turma piloto','Não iniciado','Kawe / Equipe / Rachid','Escolher turma e testar ponta a ponta.')],
        'tasks':[('t1','Validar com a operação e escolher turma piloto','Kawe / Equipe / Rachid','Pendente','Alta','Próxima revisão','m3')]
      },
      'my-novo-sistema-vendas': {
        'phase':'Implantação', 'health':'Atenção', 'status':'Em andamento',
        'objective':'Ativar o novo fluxo comercial com ata e compromissos consolidados, carteiras e contas em uso real.',
        'current_state':'Fluxo comercial consolidado e 2ª reunião realizada; ativação comprovada ainda pendente.',
        'last_advance':'2ª reunião comercial realizada; decisões e compromissos precisam ser consolidados.',
        'next_step':'Consolidar a ata e os compromissos e comprovar ativação, carteiras e contas em uso.',
        'milestones':[('m1','Ata e compromissos da 2ª reunião','Em andamento','Ana / Coordenadores','Consolidar ata e responsáveis.'),('m2','Ativação, carteiras e contas em uso','Em andamento','Ana / Coordenadores','Comprovar uso operacional real.')],
        'tasks':[('t1','Consolidar ata, compromissos e evidências de ativação','Ana / Coordenadores','Pendente','Alta','Próxima reunião','m1')]
      },
      'my-novo-sistema-entrega-anexxo': {
        'phase':'Homologação e ajustes', 'health':'Atenção', 'status':'Em desenvolvimento',
        'objective':'Homologar o Sistema de Entrega / A.NEXXO V34.4 em operação real, com correções priorizadas, acessos definidos e fluxo ponta a ponta validado.',
        'current_state':'V34.4 passou por treinamento e homologação real; vídeo, correções, acessos e homologação ponta a ponta são as frentes abertas.',
        'last_advance':'Treinamento e homologação real da V34.4 concluídos.',
        'next_step':'Analisar o vídeo, priorizar correções, definir acessos e homologar ponta a ponta.',
        'milestones':[('m1','Vídeo e priorização de correções','Em andamento','Rachid / Produto-Tecnologia','Analisar gravação e priorizar ajustes.'),('m2','Acessos e perfis','Não iniciado','Rachid / Produto-Tecnologia','Definir acessos necessários.'),('m3','Homologação ponta a ponta','Não iniciado','Rachid / Produto-Tecnologia','Validar fluxo completo em operação.')],
        'tasks':[('t1','Analisar vídeo e priorizar correções','Rachid / Produto-Tecnologia','Pendente','Alta','Próxima revisão','m1'),('t2','Definir acessos e homologar ponta a ponta','Rachid / Produto-Tecnologia','Pendente','Alta','Após priorização','m2')]
      },
      'my-sistema-comissao': {
        'phase':'Conceituação com requisitos ampliados', 'health':'Atenção', 'status':'Estruturação',
        'objective':'Definir o Sistema da Comissão com campos obrigatórios, visibilidade e passagem estruturada ao assessor.',
        'current_state':'Sem atualização operacional confirmada; campos, visibilidade e passagem permanecem em aberto.',
        'last_advance':'Reconstrução das três frentes estruturantes: campos, visibilidade e passagem.',
        'next_step':'Definir campos, visibilidade e passagem ao assessor.',
        'milestones':[('m1','Campos e informações mínimas','Não iniciado','Rachid / Ana','Definir campos obrigatórios.'),('m2','Visibilidade','Não iniciado','Rachid / Ana','Definir o que cada perfil visualiza.'),('m3','Passagem ao assessor','Não iniciado','Rachid / Ana','Definir regra e responsável pela passagem.')],
        'tasks':[('t1','Definir campos, visibilidade e passagem ao assessor','Rachid / Ana','Pendente','Alta','Próxima revisão','m1')]
      }
    }
    for pid, data in projects.items():
        p=db.session.get(PersonalProject,pid)
        if not p: continue
        for field in ('phase','health','status','objective','current_state','last_advance','next_step','deadline'):
            if field in data: setattr(p,field,data[field])
        for suffix,name,status,responsible,next_step in data['milestones']:
            mid=f'{pid}-{suffix}'; m=db.session.get(PersonalMilestone,mid)
            if not m: m=PersonalMilestone(id=mid,project_id=pid,position=int(suffix[1:])); db.session.add(m)
            m.name=name; m.status=status; m.responsible_name=responsible; m.next_step=next_step
        for suffix,title,responsible,status,priority,due,milestone_suffix in data['tasks']:
            tid=f'{pid}-{suffix}'; t=db.session.get(PersonalTask,tid)
            if not t: t=PersonalTask(id=tid,project_id=pid); db.session.add(t)
            t.title=title; t.responsible_name=responsible; t.status=status; t.priority=priority; t.due=due; t.milestone_id=f'{pid}-{milestone_suffix}'
        _history(pid,'Sistema','Reconstrução de conteúdo V7','CENTRAL DE GESTÃO - PROJETOS')

def _personal_access(user, project_id, milestone_id=None, task_id=None, permission='view'):
    if not user: return None
    p=db.session.get(PersonalProject,project_id)
    if not p: return None
    if user.id==p.owner_user_id: return 'owner'
    if p.responsible_user_id and user.id==p.responsible_user_id: return 'responsible'
    if milestone_id:
        milestone=db.session.get(PersonalMilestone,milestone_id)
        if milestone and milestone.project_id==project_id and milestone.responsible_user_id==user.id:
            return 'responsible'
    row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=milestone_id,task_id=task_id).first()
    if row: return row.permission
    if milestone_id:
        row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=milestone_id,task_id=None).first()
        if row: return row.permission
    row=PersonalAccess.query.filter_by(user_id=user.id,project_id=project_id,milestone_id=None,task_id=None).first()
    if row: return row.permission
    # A responsabilidade por um único marco dá acesso de consulta ao contêiner
    # do projeto, sem abrir os demais marcos ou registros.
    if not milestone_id and PersonalMilestone.query.filter_by(project_id=project_id,responsible_user_id=user.id,active=True).first():
        return 'view'
    return None

def _personal_can_edit(user, project_id, milestone_id=None, task_id=None):
    return _personal_access(user,project_id,milestone_id,task_id) in ('owner','responsible','edit')

def _personal_visible_projects(user):
    if not user: return []
    owned=PersonalProject.query.filter_by(owner_user_id=user.id).all()
    responsible=PersonalProject.query.filter_by(responsible_user_id=user.id).all()
    milestone_responsibility=PersonalMilestone.query.filter_by(responsible_user_id=user.id,active=True).all()
    access=PersonalAccess.query.filter_by(user_id=user.id).all()
    ids={p.id for p in owned}|{p.id for p in responsible}|{m.project_id for m in milestone_responsibility}|{a.project_id for a in access if a.project_id}
    return PersonalProject.query.filter(PersonalProject.id.in_(ids)).order_by(PersonalProject.created_at).all() if ids else []

def _personal_serialized(user, project, include_restricted=True):
    accesses=PersonalAccess.query.filter_by(user_id=user.id,project_id=project.id).all()
    owner=user.id==project.owner_user_id
    project_responsible=user.id==project.responsible_user_id
    project_wide=owner or project_responsible or any(a.milestone_id is None and a.task_id is None for a in accesses)
    delegated_milestone_ids={a.milestone_id for a in accesses if a.milestone_id and not a.task_id}
    responsible_milestone_ids={m.id for m in PersonalMilestone.query.filter_by(project_id=project.id,responsible_user_id=user.id,active=True).all()}
    milestone_ids=set(delegated_milestone_ids)|responsible_milestone_ids
    task_ids={a.task_id for a in accesses if a.task_id}
    milestones=PersonalMilestone.query.filter_by(project_id=project.id,active=True).order_by(PersonalMilestone.position).all()
    tasks=PersonalTask.query.filter_by(project_id=project.id).order_by(PersonalTask.created_at).all()
    if not project_wide:
        allowed_task_milestones={t.milestone_id for t in tasks if t.id in task_ids}
        milestone_ids|={m for m in allowed_task_milestones if m}
        milestones=[m for m in milestones if m.id in milestone_ids]
        # Um acesso a tarefa não abre as outras tarefas do mesmo marco.
        tasks=[t for t in tasks if t.id in task_ids or t.milestone_id in delegated_milestone_ids or t.milestone_id in responsible_milestone_ids]
    project_responsible_name=project.responsible_name or ''
    milestone_names={m.id:m.name for m in milestones}
    visible_milestone_ids=[m.id for m in milestones]
    milestone_records=(PersonalMilestoneRecord.query
        .filter(PersonalMilestoneRecord.milestone_id.in_(visible_milestone_ids))
        .order_by(PersonalMilestoneRecord.created_at.desc(), PersonalMilestoneRecord.id.desc()).all()
        if visible_milestone_ids else [])
    records_by_milestone={mid:[] for mid in visible_milestone_ids}
    for record in milestone_records:
        records_by_milestone.setdefault(record.milestone_id,[]).append({
            'id':record.id,'author':record.author,'body':record.body,
            'at':record.created_at.isoformat(),
        })
    return {
        'id':project.id,'name':project.name,'owner':project_responsible_name,'managedBy':project.owner_name,
        'responsibleUserId':project.responsible_user_id,'visibility':project.visibility,'phase':project.phase,
        'health':project.health,'status':project.status,'objective':project.objective,'current':project.current_state,
        'lastAdvance':project.last_advance,'next':project.next_step,'priority':project.priority,'deadline':project.deadline,
        'restricted':not project_wide,'canEdit':_personal_can_edit(user,project.id),'canAssign':owner,
        'milestones':[{
            'id':m.id,'name':m.name,'category':m.category,'status':m.status,'health':m.health,
            'owner':m.responsible_name,'effectiveOwner':m.responsible_name or project_responsible_name,
            'inheritsProjectOwner':not bool(m.responsible_name),'responsibleUserId':m.responsible_user_id,
            'next':m.next_step,'deadline':m.deadline,'notes':m.notes,
            'conclusion':m.conclusion or '',
            'concludedAt':m.concluded_at.isoformat() if m.concluded_at else '',
            'records':records_by_milestone.get(m.id,[]),
            'canEdit':_personal_can_edit(user,project.id,m.id),'canAssign':owner,
        } for m in milestones],
        'tasks':[{
            'id':t.id,'milestoneId':t.milestone_id,'milestoneName':milestone_names.get(t.milestone_id,''),
            'title':t.title,'owner':t.responsible_name or project_responsible_name,'status':t.status,
            'priority':t.priority,'due':t.due,'canEdit':_personal_can_edit(user,project.id,t.milestone_id,t.id),
        } for t in tasks],
        'journal':([] if not project_wide else [{'id':j.id,'title':j.title,'body':j.body,'next':j.next_step,'author':j.author,'at':j.created_at.isoformat()} for j in PersonalJournal.query.filter_by(project_id=project.id).order_by(PersonalJournal.created_at.desc()).all()]),
        'milestoneRecords':([{
            'id':r.id,'milestoneId':r.milestone_id,'milestoneName':milestone_names.get(r.milestone_id,''),
            'author':r.author,'body':r.body,'at':r.created_at.isoformat(),
        } for r in milestone_records]),
        'history':([] if not project_wide else [{'author':h.author,'action':h.action,'detail':h.detail,'at':h.created_at.isoformat()} for h in PersonalHistory.query.filter_by(project_id=project.id).order_by(PersonalHistory.created_at.desc()).all()]),
    }

# Usuários de consulta: enxergam toda a transformação, mas não possuem projeto e não editam nada.
_VIEWER_USERS = [
    ('julia', 'Julia'),
    ('michele', 'Michele'),
    ('kawe', 'Kawe'),
    ('cole', 'Cole'),
    ('lucas', 'Lucas'),
    ('julio', 'Julio'),
    ('felippe', 'Felippe Mancuzo'),
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

def _active_personal_user(username):
    username=(username or '').strip().lower()
    if not username:
        return None
    user=User.query.filter_by(username=username,active=True).first()
    if not user:
        abort(Response(json.dumps({'error':'Usuário ativo não encontrado.'},ensure_ascii=False),status=400,mimetype='application/json'))
    return user

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
        if 'responsibleUsername' in body:
            if u.id!=p.owner_user_id: abort(403)
            responsible=_active_personal_user(body.get('responsibleUsername'))
            p.responsible_user_id=responsible.id if responsible else None
            p.responsible_name=responsible.display_name if responsible else ''
            if responsible and p.visibility=='Privado': p.visibility='Delegado'
            _history(project_id,u.display_name,'Responsável do projeto atualizado',p.responsible_name or 'Sem responsável')
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
    changes=[]
    if 'status' in body:
        status=(body.get('status') or '').strip()
        if status not in ('Não iniciado','Em andamento','Em risco','Concluído'): return jsonify({'error':'Status inválido.'}),400
        if status!=m.status: changes.append(f'Status: {m.status or "—"} → {status}')
        m.status=status
    if 'category' in body: m.category=(body.get('category') or '').strip()
    if 'next' in body: m.next_step=(body.get('next') or '').strip()
    if 'deadline' in body:
        deadline=(body.get('deadline') or '').strip()
        if deadline!=m.deadline: changes.append(f'Prazo: {m.deadline or "—"} → {deadline or "—"}')
        m.deadline=deadline
    if 'notes' in body: m.notes=(body.get('notes') or '').strip()
    if 'conclusion' in body:
        conclusion=(body.get('conclusion') or '').strip()
        if conclusion!=m.conclusion: changes.append('Conclusão / resultado atualizado')
        m.conclusion=conclusion
    if m.status=='Concluído' and not m.concluded_at:
        m.concluded_at=datetime.utcnow()
    elif m.status!='Concluído':
        m.concluded_at=None
    record=(body.get('record') or '').strip()
    if record:
        db.session.add(PersonalMilestoneRecord(project_id=m.project_id,milestone_id=m.id,author=u.display_name,body=record))
    if 'responsibleUsername' in body:
        project=db.session.get(PersonalProject,m.project_id)
        if u.id!=project.owner_user_id: abort(403)
        responsible=_active_personal_user(body.get('responsibleUsername'))
        m.responsible_user_id=responsible.id if responsible else None
        m.responsible_name=responsible.display_name if responsible else ''
        _history(m.project_id,u.display_name,'Responsável do marco atualizado',f'{m.name}: {m.responsible_name or "herda o projeto"}')
    if changes:
        _history(m.project_id,u.display_name,f'Marco atualizado · {m.name}',' · '.join(changes))
    db.session.commit(); return jsonify({'ok':True})

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
        _ensure_personal_v8_schema()
        _create_logical_backup_once()
        _seed_personal_projects_once()
        _reconstruct_personal_content_v7_once()
        _create_personal_v8_backup_once()
        _restore_personal_milestones_v8_once()
        db.session.commit()

_initialize_unified_central()


# Roadmap do Sucesso e gravação longa de reuniões
import project_success
project_success.register(__import__("app"))

# Histórico somente leitura de reuniões
import meeting_history
meeting_history.register(__import__("app"))

# Validação não bloqueante da IA em uma reunião histórica migrada
import legacy_ai_validation
legacy_ai_validation.start()
