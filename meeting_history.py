import json
from datetime import datetime

from flask import jsonify
from sqlalchemy import text


def register(app_module):
    app = app_module.app
    db = app_module.db

    def _state():
        return db.session.get(app_module.AppState, 1)

    def _project_name_map(payload):
        return {p.get('id'): p.get('name') or p.get('id') for p in (payload.get('projects') or [])}

    def _visible_project_ids(user, payload):
        if not user:
            return set()
        if user.role in ('admin', 'direction'):
            return {p.get('id') for p in (payload.get('projects') or [])}
        if user.project_id:
            return {user.project_id}
        # Visualizadores não entram no Modo Reunião, mas se acessarem a API,
        # preservamos a política de consulta geral já usada no sistema.
        if user.role == 'viewer':
            return {p.get('id') for p in (payload.get('projects') or [])}
        return set()

    def _official_meeting(payload, session_id):
        for m in payload.get('meetings') or []:
            if (m.get('audioSessionId') or '') == session_id:
                return m
        return None

    def _duration_seconds(started_at, ended_at):
        if not started_at:
            return 0
        end = ended_at or datetime.utcnow()
        try:
            return max(0, int((end - started_at).total_seconds()))
        except Exception:
            return 0

    @app.route('/api/meeting/history')
    @app_module.login_required
    def meeting_history_list():
        user = app_module.current_user()
        state = _state()
        payload = state.payload if state else {}
        names = _project_name_map(payload)
        visible_ids = _visible_project_ids(user, payload)
        if not visible_ids:
            return jsonify({'meetings': []})

        rows = db.session.execute(text("""
            SELECT s.id, s.project_id, s.created_by, s.status, s.started_at, s.ended_at,
                   COUNT(g.id) AS segment_count
              FROM kaz_meeting_audio_sessions s
              JOIN kaz_meeting_audio_segments g ON g.session_id = s.id
             WHERE s.project_id = ANY(:project_ids)
             GROUP BY s.id, s.project_id, s.created_by, s.status, s.started_at, s.ended_at
             ORDER BY s.started_at DESC
        """), {'project_ids': list(visible_ids)}).mappings().all()

        meetings = []
        for row in rows:
            saved = _official_meeting(payload, row['id'])
            meetings.append({
                'id': row['id'],
                'date': row['started_at'].isoformat() if row['started_at'] else '',
                'projectId': row['project_id'],
                'projectName': names.get(row['project_id'], row['project_id']),
                'createdBy': row['created_by'],
                'durationSeconds': _duration_seconds(row['started_at'], row['ended_at']),
                'registered': bool(saved),
                'aiProcessed': bool(saved and saved.get('aiProcessed')),
            })
        return jsonify({'meetings': meetings})

    @app.route('/api/meeting/history/<session_id>')
    @app_module.login_required
    def meeting_history_detail(session_id):
        user = app_module.current_user()
        state = _state()
        payload = state.payload if state else {}
        names = _project_name_map(payload)
        visible_ids = _visible_project_ids(user, payload)

        row = db.session.execute(text("""
            SELECT id, project_id, created_by, status, started_at, ended_at
              FROM kaz_meeting_audio_sessions
             WHERE id = :session_id
        """), {'session_id': session_id}).mappings().first()
        if not row:
            return jsonify({'error': 'Reunião não encontrada.'}), 404
        if row['project_id'] not in visible_ids:
            return jsonify({'error': 'Sem permissão para consultar esta reunião.'}), 403

        segments = db.session.execute(text("""
            SELECT position, size, transcript
              FROM kaz_meeting_audio_segments
             WHERE session_id = :session_id
             ORDER BY position
        """), {'session_id': session_id}).mappings().all()

        saved = _official_meeting(payload, session_id)
        transcript = ''
        if saved and (saved.get('transcript') or '').strip():
            transcript = (saved.get('transcript') or '').strip()
        else:
            transcript = '\n\n'.join((s['transcript'] or '').strip() for s in segments if (s['transcript'] or '').strip())

        previous_review = (saved or {}).get('previousReview')
        if not isinstance(previous_review, dict):
            previous_review = None

        review = {
            'summary': (saved or {}).get('summary') or '',
            'topics': (saved or {}).get('topics') or (saved or {}).get('notes') or '',
            'decisions': (saved or {}).get('decisions') or '',
            'nextSteps': (saved or {}).get('nextSteps') or '',
            'dependencies': (saved or {}).get('dependencies') or '',
            'commitment': (saved or {}).get('nextWeek') or '',
            'aiProcessed': bool((saved or {}).get('aiProcessed')),
        }

        return jsonify({
            'id': row['id'],
            'date': row['started_at'].isoformat() if row['started_at'] else '',
            'projectId': row['project_id'],
            'projectName': names.get(row['project_id'], row['project_id']),
            'createdBy': row['created_by'],
            'durationSeconds': _duration_seconds(row['started_at'], row['ended_at']),
            'registered': bool(saved),
            'previousReview': previous_review,
            'transcript': transcript,
            'review': review,
            'segments': [{
                'position': s['position'],
                'size': s['size'],
                'transcribed': bool((s['transcript'] or '').strip()),
                'url': f"/api/meeting/audio-sessions/{session_id}/segments/{s['position']}/audio",
            } for s in segments],
        })


    # Garante que as próximas reuniões guardem um retrato da etapa 2.
    original_create_meeting = app.view_functions.get('create_meeting')

    @app_module.login_required
    def create_meeting_with_previous_review():
        # A função já registrada em project_success faz toda a validação e persistência.
        # Antes dela rodar, injetamos no body o snapshot atual da etapa 2.
        from flask import request
        if request.method != 'POST':
            return original_create_meeting()

        body = request.get_json(silent=True) or {}
        project_id = (body.get('projectId') or '').strip()
        if project_id and not body.get('previousReview'):
            state = _state()
            payload = state.payload if state else {}
            project = app_module.find_project(payload, project_id)
            if project:
                commitments = []
                for c in project.get('weeklyCommitments') or []:
                    if c.get('status') in ('Aberto', 'Parcial', 'Realizado', 'Não realizado'):
                        commitments.append({
                            'text': c.get('text') or '',
                            'status': c.get('status') or 'Aberto',
                            'author': c.get('author') or '',
                            'createdAt': c.get('createdAt') or '',
                        })
                dependencies = []
                for d in payload.get('dependencies') or []:
                    if d.get('projectId') == project_id and d.get('status') != 'Resolvida':
                        dependencies.append({
                            'subject': d.get('subject') or d.get('title') or '',
                            'status': d.get('status') or '',
                            'director': d.get('director') or d.get('assignedDirector') or '',
                            'deadline': d.get('deadline') or '',
                        })
                body['previousReview'] = {
                    'commitments': commitments,
                    'dependencies': dependencies,
                    'capturedAt': app_module.now_iso(),
                }

            # Flask já consumiu o JSON; sobrescrevemos o cache interno usado por get_json.
            request._cached_json = (body, body)

        response = original_create_meeting()

        # A implementação anterior não conhecia previousReview. Se a reunião foi salva,
        # anexamos o snapshot ao registro correspondente em uma segunda transação curta.
        try:
            if project_id and body.get('previousReview'):
                state = db.session.execute(
                    app_module.select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
                ).scalar_one()
                payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                session_id = (body.get('audioSessionId') or '').strip()
                target = None
                if session_id:
                    target = next((m for m in payload.get('meetings', []) if m.get('audioSessionId') == session_id), None)
                if not target:
                    candidates = [m for m in payload.get('meetings', []) if m.get('projectId') == project_id]
                    target = candidates[-1] if candidates else None
                if target and not target.get('previousReview'):
                    target['previousReview'] = body.get('previousReview')
                    state.payload = payload
                    state.revision = int(state.revision or 0) + 1
                    state.updated_by = app_module.current_user().display_name
                    state.updated_at = datetime.utcnow()
                    db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Falha ao anexar snapshot da etapa 2 à reunião')
        return response

    if original_create_meeting:
        app.view_functions['create_meeting'] = create_meeting_with_previous_review
