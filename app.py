import gzip, os, secrets
from flask import render_template, jsonify, request, abort, Response
from sqlalchemy import select, text as sql_text
from werkzeug.security import generate_password_hash

# Carrega o núcleo estável do sistema. A interface V5 usa arquivos HTML/JS normais.
_core_path = os.path.join(os.path.dirname(__file__), 'app_core.py.gz')
with gzip.open(_core_path, 'rt', encoding='utf-8') as _f:
    _source = _f.read()
exec(compile(_source, _core_path, 'exec'), globals(), globals())

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
