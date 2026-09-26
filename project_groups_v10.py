import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime

from flask import abort, jsonify, request
from sqlalchemy import select


DEFAULT_WORKGROUPS = [
    {'id': 'transformacao-kaz', 'name': 'Transformação KAZ', 'active': True, 'order': 10, 'system': True},
    {'id': 'transformacao-galleria', 'name': 'Transformação Galleria', 'active': True, 'order': 20, 'system': False},
    {'id': 'pessoal', 'name': 'Pessoal', 'active': True, 'order': 30, 'system': False},
    {'id': 'sem-grupo', 'name': 'Sem grupo', 'active': True, 'order': 999, 'system': True},
]


def _slug(value):
    raw = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    raw = re.sub(r'[^a-zA-Z0-9]+', '-', raw).strip('-').lower()
    return raw or 'grupo'


def register(app_module):
    app = app_module.app
    db = app_module.db

    def _state_locked():
        return db.session.execute(
            select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
        ).scalar_one()

    def _deep(value):
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _active_users():
        return app_module.User.query.filter_by(active=True).order_by(app_module.User.display_name).all()

    def _user_by_username(username):
        username = (username or '').strip().lower()
        if not username:
            return None
        return app_module.User.query.filter_by(username=username, active=True).first()

    def _group_map(payload):
        return {g.get('id'): g for g in (payload.get('workgroups') or [])}

    def _ensure_groups(payload):
        existing = {g.get('id'): g for g in (payload.get('workgroups') or []) if g.get('id')}
        rows = []
        for default in DEFAULT_WORKGROUPS:
            item = existing.pop(default['id'], None)
            if item:
                merged = dict(default)
                merged.update(item)
                rows.append(merged)
            else:
                rows.append(dict(default))
        rows.extend(existing.values())
        rows.sort(key=lambda g: (int(g.get('order') or 999), str(g.get('name') or '')))
        payload['workgroups'] = rows

    def _iso(value):
        if not value:
            return ''
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _backup_once(state):
        key = 'unified-projects-workgroups-v10'
        if app_module.MigrationBackup.query.filter_by(backup_key=key).first():
            return False

        personal_projects = app_module.PersonalProject.query.order_by(app_module.PersonalProject.id).all()
        project_ids = [p.id for p in personal_projects]
        snapshot = {
            'kaz_revision': state.revision,
            'kaz_payload': _deep(state.payload),
            'personal_projects': [
                {c.name: _iso(getattr(p, c.name)) for c in app_module.PersonalProject.__table__.columns}
                for p in personal_projects
            ],
            'personal_milestones': [
                {c.name: _iso(getattr(m, c.name)) for c in app_module.PersonalMilestone.__table__.columns}
                for m in app_module.PersonalMilestone.query.filter(
                    app_module.PersonalMilestone.project_id.in_(project_ids)
                ).order_by(app_module.PersonalMilestone.project_id, app_module.PersonalMilestone.position).all()
            ] if project_ids else [],
            'personal_tasks': [
                {c.name: _iso(getattr(t, c.name)) for c in app_module.PersonalTask.__table__.columns}
                for t in app_module.PersonalTask.query.filter(
                    app_module.PersonalTask.project_id.in_(project_ids)
                ).order_by(app_module.PersonalTask.project_id, app_module.PersonalTask.created_at).all()
            ] if project_ids else [],
            'personal_journal': [
                {c.name: _iso(getattr(j, c.name)) for c in app_module.PersonalJournal.__table__.columns}
                for j in app_module.PersonalJournal.query.filter(
                    app_module.PersonalJournal.project_id.in_(project_ids)
                ).order_by(app_module.PersonalJournal.project_id, app_module.PersonalJournal.created_at).all()
            ] if project_ids else [],
            'personal_history': [
                {c.name: _iso(getattr(h, c.name)) for c in app_module.PersonalHistory.__table__.columns}
                for h in app_module.PersonalHistory.query.filter(
                    app_module.PersonalHistory.project_id.in_(project_ids)
                ).order_by(app_module.PersonalHistory.project_id, app_module.PersonalHistory.created_at).all()
            ] if project_ids else [],
        }
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
        db.session.add(app_module.MigrationBackup(
            backup_key=key,
            payload=snapshot,
            checksum=hashlib.sha256(raw).hexdigest(),
        ))
        return True

    def _migrate_personal_project(row, records_by_milestone, histories, journals):
        milestones = []
        for milestone in app_module.PersonalMilestone.query.filter_by(
            project_id=row.id, active=True
        ).order_by(app_module.PersonalMilestone.position, app_module.PersonalMilestone.created_at).all():
            memos = []
            if (milestone.notes or '').strip():
                memos.append({
                    'at': _iso(milestone.created_at),
                    'author': 'Sistema',
                    'text': milestone.notes.strip(),
                })
            for record in records_by_milestone.get(milestone.id, []):
                memos.append({
                    'at': _iso(record.created_at),
                    'author': record.author,
                    'text': record.body,
                })
            milestones.append({
                'id': milestone.id,
                'name': milestone.name,
                'status': milestone.status or 'Não iniciado',
                'deadline': milestone.deadline or '',
                'conclusion': milestone.conclusion or '',
                'concludedAt': _iso(milestone.concluded_at),
                'memos': memos,
                'files': [],
                'legacyCategory': milestone.category or '',
                'legacyHealth': milestone.health or '',
                'legacyResponsibleName': milestone.responsible_name or '',
                'legacyNextStep': milestone.next_step or '',
            })

        general_memos = []
        for label, value in [
            ('Situação registrada', row.current_state),
            ('Último avanço registrado', row.last_advance),
            ('Próximo passo registrado', row.next_step),
        ]:
            if (value or '').strip():
                general_memos.append({
                    'at': _iso(row.updated_at or row.created_at),
                    'author': 'Sistema',
                    'text': f'{label}: {value.strip()}',
                })
        for journal in journals:
            body = (journal.body or '').strip()
            if body:
                text_value = f'{journal.title}: {body}'
                if (journal.next_step or '').strip():
                    text_value += f' | Próximo passo: {journal.next_step.strip()}'
                general_memos.append({
                    'at': _iso(journal.created_at),
                    'author': journal.author,
                    'text': text_value,
                })

        project_history = []
        for history in histories:
            text_value = history.action
            if (history.detail or '').strip():
                text_value += f' · {history.detail.strip()}'
            project_history.append({
                'at': _iso(history.created_at),
                'author': history.author,
                'text': text_value,
            })

        return {
            'id': row.id,
            'name': row.name,
            'owner': '',
            'responsibleName': '',
            'responsibleUsername': '',
            'workgroupId': 'sem-grupo',
            'status': row.status or 'Não iniciado',
            'objective': row.objective or '',
            'validated': False,
            'lastUpdate': _iso(row.updated_at or row.created_at),
            'milestones': milestones,
            'generalMemos': general_memos,
            'scopeDefined': False,
            'milestonesLocked': False,
            'weeklyCommitments': [],
            'milestonesLockedAt': '',
            'milestonesLockedBy': '',
            'files': [],
            'history': project_history,
            'legacy': {
                'source': 'Minha Gestão',
                'ownerName': row.owner_name or '',
                'phase': row.phase or '',
                'health': row.health or '',
                'priority': row.priority or '',
                'deadline': row.deadline or '',
                'visibility': row.visibility or '',
            },
        }

    def _migrate_once():
        state = db.session.get(app_module.AppState, 1)
        if not state:
            return
        payload = _deep(state.payload or {})
        changed = False
        created_backup = _backup_once(state)
        _ensure_groups(payload)

        users = _active_users()
        display_to_username = {
            (u.display_name or '').strip().casefold(): u.username
            for u in users if (u.display_name or '').strip()
        }

        # Todo projeto que já estava na Transformação KAZ permanece nesse grupo.
        for project in payload.get('projects', []):
            if not project.get('workgroupId'):
                project['workgroupId'] = 'transformacao-kaz'
                changed = True
            if 'responsibleUsername' not in project:
                owner = (project.get('owner') or '').strip()
                username = display_to_username.get(owner.casefold(), '') if owner else ''
                project['responsibleUsername'] = username
                project['responsibleName'] = owner if username else ''
                changed = True
            elif 'responsibleName' not in project:
                username = (project.get('responsibleUsername') or '').strip().lower()
                user = next((u for u in users if u.username == username), None)
                project['responsibleName'] = user.display_name if user else (project.get('owner') or '')
                changed = True

        existing_ids = {p.get('id') for p in payload.get('projects', [])}
        personal_rows = app_module.PersonalProject.query.order_by(app_module.PersonalProject.created_at).all()
        personal_ids = [p.id for p in personal_rows]

        milestone_records = app_module.PersonalMilestoneRecord.query.filter(
            app_module.PersonalMilestoneRecord.project_id.in_(personal_ids)
        ).order_by(app_module.PersonalMilestoneRecord.created_at).all() if personal_ids else []
        records_by_milestone = {}
        for record in milestone_records:
            records_by_milestone.setdefault(record.milestone_id, []).append(record)

        histories_by_project = {}
        journals_by_project = {}
        if personal_ids:
            for history in app_module.PersonalHistory.query.filter(
                app_module.PersonalHistory.project_id.in_(personal_ids)
            ).order_by(app_module.PersonalHistory.created_at).all():
                histories_by_project.setdefault(history.project_id, []).append(history)
            for journal in app_module.PersonalJournal.query.filter(
                app_module.PersonalJournal.project_id.in_(personal_ids)
            ).order_by(app_module.PersonalJournal.created_at).all():
                journals_by_project.setdefault(journal.project_id, []).append(journal)

        for personal in personal_rows:
            if personal.id in existing_ids:
                continue
            payload.setdefault('projects', []).append(_migrate_personal_project(
                personal,
                records_by_milestone,
                histories_by_project.get(personal.id, []),
                journals_by_project.get(personal.id, []),
            ))
            existing_ids.add(personal.id)
            changed = True

        # V11: Minha Gestão começa sem pendências herdadas da antiga estrutura.
        # Guardamos exatamente o que foi removido para permitir auditoria/rollback,
        # mas não voltamos a migrar personal_tasks para dependencies.
        cleanup_key = 'cleanup-my-management-dependencies-v11'
        if not app_module.MigrationBackup.query.filter_by(backup_key=cleanup_key).first():
            unassigned_ids = {
                p.get('id')
                for p in payload.get('projects', [])
                if p.get('id') and not (p.get('responsibleUsername') or '').strip()
            }
            removed_dependencies = [
                d for d in (payload.get('dependencies') or [])
                if d.get('projectId') in unassigned_ids
            ]
            snapshot = {
                'project_ids': sorted(unassigned_ids),
                'removed_dependencies': _deep(removed_dependencies),
                'removed_count': len(removed_dependencies),
                'created_at': datetime.utcnow().isoformat(),
            }
            raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
            db.session.add(app_module.MigrationBackup(
                backup_key=cleanup_key,
                payload=snapshot,
                checksum=hashlib.sha256(raw).hexdigest(),
            ))
            if removed_dependencies:
                payload['dependencies'] = [
                    d for d in (payload.get('dependencies') or [])
                    if d.get('projectId') not in unassigned_ids
                ]
            changed = True

        if changed or created_backup or payload != (state.payload or {}):
            state.payload = payload
            state.revision = int(state.revision or 0) + 1
            state.updated_by = 'Sistema · Projetos Unificados V10'
            state.updated_at = datetime.utcnow()
            db.session.commit()

    def user_project_ids(user, payload=None):
        if not user:
            return set()
        if payload is None:
            state = db.session.get(app_module.AppState, 1)
            payload = state.payload if state else {}

        projects = payload.get('projects') or []
        username = (user.username or '').strip().lower()

        # Rachid é o único sócio com visão transversal de todos os grupos.
        if username == 'rachid':
            return {p.get('id') for p in projects if p.get('id')}

        # Demais sócios/diretores e visualizadores acompanham apenas Transformação KAZ.
        if user.role in ('admin', 'direction', 'viewer'):
            return {
                p.get('id') for p in projects
                if p.get('id') and (p.get('workgroupId') or 'sem-grupo') == 'transformacao-kaz'
            }

        # Usuários operacionais veem apenas projetos efetivamente atribuídos a eles.
        ids = {
            p.get('id') for p in projects
            if p.get('id')
            and (p.get('responsibleUsername') or '').strip().lower() == username
        }
        # Compatibilidade temporária com o campo legado project_id.
        if user.project_id and any(
            p.get('id') == user.project_id
            and (
                (p.get('responsibleUsername') or '').strip().lower() == username
                or not (p.get('responsibleUsername') or '').strip()
            )
            for p in projects
        ):
            ids.add(user.project_id)
        return ids

    def can_edit_project_v10(user, project_id):
        if not user:
            return False
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        project = app_module.find_project(payload, project_id)
        if not project:
            return False

        username = (user.username or '').strip().lower()
        if username == 'rachid':
            return True

        if user.role in ('admin', 'direction'):
            return (project.get('workgroupId') or 'sem-grupo') == 'transformacao-kaz'

        if user.role == 'viewer':
            return False

        responsible = (project.get('responsibleUsername') or '').strip().lower()
        if responsible:
            return responsible == username

        return bool(user.project_id and user.project_id == project_id)

    def _filtered_payload_for_user(payload, user):
        data = _deep(payload or {})
        if not user:
            data['projects'] = []
            data['dependencies'] = []
            data['meetings'] = []
            data['workgroups'] = []
            return data

        username = (user.username or '').strip().lower()
        if username == 'rachid':
            return data

        visible_ids = user_project_ids(user, data)
        data['projects'] = [
            p for p in (data.get('projects') or [])
            if p.get('id') in visible_ids
        ]
        data['dependencies'] = [
            d for d in (data.get('dependencies') or [])
            if d.get('projectId') in visible_ids
        ]
        data['meetings'] = [
            m for m in (data.get('meetings') or [])
            if m.get('projectId') in visible_ids
        ]

        visible_group_ids = {
            (p.get('workgroupId') or 'sem-grupo')
            for p in data.get('projects') or []
        }
        data['workgroups'] = [
            g for g in (data.get('workgroups') or [])
            if g.get('id') in visible_group_ids
        ]
        return data

    # Torna a regra disponível aos módulos antigos sem duplicar lógica.
    app_module.user_project_ids = user_project_ids
    app_module.can_edit_project = can_edit_project_v10

    with app.app_context():
        _migrate_once()

    # Protege também o estado entregue ao navegador, não apenas a interface.
    def _v10_index():
        state = db.session.get(app_module.AppState, 1)
        user = app_module.current_user()
        payload = _filtered_payload_for_user(state.payload if state else {}, user)
        return app_module.render_template(
            'index.html',
            initial_state=payload,
            revision=state.revision if state else 0,
            user=app_module.public_user(user),
            csrf=app_module.session['csrf'],
            directors=app_module.DIRECTOR_NAMES,
        )
    app.view_functions['index'] = app_module.login_required(_v10_index)

    state_endpoint = next(
        (
            rule.endpoint
            for rule in app.url_map.iter_rules()
            if rule.rule == '/api/state' and 'GET' in rule.methods
        ),
        None,
    )
    if state_endpoint:
        def _v10_state():
            state = db.session.get(app_module.AppState, 1)
            user = app_module.current_user()
            return jsonify({
                'state': _filtered_payload_for_user(state.payload if state else {}, user),
                'revision': state.revision if state else 0,
            })
        app.view_functions[state_endpoint] = app_module.login_required(_v10_state)

    @app.before_request
    def _v10_dependency_scope_guard():
        path = request.path or ''
        if not path.startswith('/api/dependencies'):
            return None

        user = app_module.current_user()
        if not user or (user.username or '').strip().lower() == 'rachid':
            return None

        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        project_id = ''

        if path.rstrip('/') == '/api/dependencies' and request.method == 'POST':
            body = request.get_json(silent=True) or {}
            project_id = (body.get('projectId') or '').strip()
        else:
            match = re.match(r'^/api/dependencies/([^/]+)', path)
            if match:
                dependency_id = match.group(1)
                dependency = next(
                    (
                        item for item in (payload.get('dependencies') or [])
                        if str(item.get('id')) == str(dependency_id)
                    ),
                    None,
                )
                project_id = (dependency or {}).get('projectId') or ''

        if project_id and project_id not in user_project_ids(user, payload):
            abort(403)
        return None

    def _require_direction(user):
        if not user or user.role not in ('admin', 'direction'):
            abort(403)

    def _require_rachid(user):
        if not user or (user.username or '').strip().lower() != 'rachid':
            abort(403)

    @app.route('/api/project-organization')
    @app_module.login_required
    def project_organization():
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        groups = payload.get('workgroups') or []
        if (user.username or '').strip().lower() != 'rachid':
            groups = [g for g in groups if g.get('id') == 'transformacao-kaz']
        return jsonify({
            'workgroups': sorted(
                groups,
                key=lambda g: (int(g.get('order') or 999), str(g.get('name') or ''))
            ),
            'users': [
                {
                    'id': u.id,
                    'username': u.username,
                    'display_name': u.display_name,
                    'role': u.role,
                }
                for u in _active_users()
            ] if user and user.role in ('admin', 'direction') else [],
        })

    @app.route('/api/projects/<project_id>/organization', methods=['POST'])
    @app_module.login_required
    def update_project_organization(project_id):
        app_module.require_csrf()
        user = app_module.current_user()
        _require_direction(user)
        body = request.get_json(force=True) or {}

        state = _state_locked()
        payload = _deep(state.payload or {})
        project = app_module.find_project(payload, project_id)
        if not project:
            abort(404)

        is_rachid = (user.username or '').strip().lower() == 'rachid'
        current_group_id = project.get('workgroupId') or 'sem-grupo'
        if not is_rachid and current_group_id != 'transformacao-kaz':
            abort(403)

        if 'workgroupId' in body:
            group_id = (body.get('workgroupId') or 'sem-grupo').strip()
            group = _group_map(payload).get(group_id)
            if not group:
                return jsonify({'error': 'Grupo de trabalho não encontrado.'}), 400
            if not is_rachid and group_id != 'transformacao-kaz':
                abort(403)
            project['workgroupId'] = group_id

        if 'responsibleUsername' in body:
            username = (body.get('responsibleUsername') or '').strip().lower()
            responsible = _user_by_username(username)
            if username and not responsible:
                return jsonify({'error': 'Usuário ativo não encontrado.'}), 400
            project['responsibleUsername'] = responsible.username if responsible else ''
            project['responsibleName'] = responsible.display_name if responsible else ''
            project['owner'] = responsible.display_name if responsible else ''

            # Mantém project_id antigo apenas como compatibilidade com telas legadas.
            if responsible and not responsible.project_id:
                responsible.project_id = project_id
            for other in _active_users():
                if other.id != (responsible.id if responsible else None) and other.project_id == project_id:
                    alternatives = [
                        p.get('id') for p in payload.get('projects', [])
                        if (p.get('responsibleUsername') or '').lower() == (other.username or '').lower()
                        and p.get('id') != project_id
                    ]
                    other.project_id = alternatives[0] if alternatives else None

        project['lastUpdate'] = app_module.now_iso()
        project.setdefault('history', []).append({
            'at': app_module.now_iso(),
            'author': user.display_name,
            'text': f"Organização atualizada · grupo: {_group_map(payload).get(project.get('workgroupId'), {}).get('name', 'Sem grupo')} · responsável: {project.get('responsibleName') or 'Minha Gestão'}",
        })

        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'revision': state.revision})

    @app.route('/api/workgroups', methods=['POST'])
    @app_module.login_required
    def create_workgroup():
        app_module.require_csrf()
        user = app_module.current_user()
        _require_rachid(user)
        body = request.get_json(force=True) or {}
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Informe o nome do grupo de trabalho.'}), 400

        state = _state_locked()
        payload = _deep(state.payload or {})
        _ensure_groups(payload)
        ids = {g.get('id') for g in payload.get('workgroups') or []}
        base = _slug(name)
        group_id = base
        counter = 2
        while group_id in ids:
            group_id = f'{base}-{counter}'
            counter += 1
        next_order = max([int(g.get('order') or 0) for g in payload.get('workgroups') or [] if g.get('id') != 'sem-grupo'] + [0]) + 10
        row = {'id': group_id, 'name': name, 'active': True, 'order': next_order, 'system': False}
        payload.setdefault('workgroups', []).append(row)

        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'workgroup': row, 'revision': state.revision})

    @app.route('/api/workgroups/<group_id>', methods=['POST'])
    @app_module.login_required
    def update_workgroup(group_id):
        app_module.require_csrf()
        user = app_module.current_user()
        _require_rachid(user)
        body = request.get_json(force=True) or {}

        state = _state_locked()
        payload = _deep(state.payload or {})
        _ensure_groups(payload)
        group = _group_map(payload).get(group_id)
        if not group:
            abort(404)
        if 'name' in body:
            name = (body.get('name') or '').strip()
            if not name:
                return jsonify({'error': 'O nome não pode ficar vazio.'}), 400
            group['name'] = name
        if 'active' in body and group_id not in ('transformacao-kaz', 'sem-grupo'):
            group['active'] = bool(body.get('active'))
        if 'order' in body:
            try:
                group['order'] = int(body.get('order'))
            except Exception:
                return jsonify({'error': 'Ordem inválida.'}), 400

        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'workgroup': group, 'revision': state.revision})

    @app.route('/api/projects-v10', methods=['POST'])
    @app_module.login_required
    def create_project_v10():
        app_module.require_csrf()
        user = app_module.current_user()
        _require_direction(user)
        body = request.get_json(force=True) or {}
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Informe o nome do projeto.'}), 400

        state = _state_locked()
        payload = _deep(state.payload or {})
        _ensure_groups(payload)
        group_id = (body.get('workgroupId') or 'sem-grupo').strip()
        if group_id not in _group_map(payload):
            return jsonify({'error': 'Grupo de trabalho inválido.'}), 400
        if (user.username or '').strip().lower() != 'rachid' and group_id != 'transformacao-kaz':
            abort(403)

        responsible = _user_by_username(body.get('responsibleUsername'))
        base = _slug(name)
        existing = {p.get('id') for p in payload.get('projects') or []}
        project_id = base
        counter = 2
        while project_id in existing:
            project_id = f'{base}-{counter}'
            counter += 1

        project = {
            'id': project_id,
            'name': name,
            'owner': responsible.display_name if responsible else '',
            'responsibleName': responsible.display_name if responsible else '',
            'responsibleUsername': responsible.username if responsible else '',
            'workgroupId': group_id,
            'status': 'Não iniciado',
            'objective': (body.get('objective') or '').strip(),
            'validated': False,
            'lastUpdate': app_module.now_iso(),
            'milestones': [],
            'generalMemos': [],
            'scopeDefined': False,
            'milestonesLocked': False,
            'weeklyCommitments': [],
            'milestonesLockedAt': '',
            'milestonesLockedBy': '',
            'files': [],
            'history': [{
                'at': app_module.now_iso(),
                'author': user.display_name,
                'text': 'Projeto criado.',
            }],
        }
        payload.setdefault('projects', []).append(project)
        if responsible and not responsible.project_id:
            responsible.project_id = project_id

        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'project': project, 'revision': state.revision})
