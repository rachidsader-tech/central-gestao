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
              LEFT JOIN kaz_meeting_audio_segments g ON g.session_id = s.id
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
                'durationSeconds': _duration_seconds(row['started_at'], row['ended_at']) if row['segment_count'] else None,
                'hasAudio': bool(row['segment_count']),
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
            'aiTestPreview': (saved or {}).get('migrationAiPreview'),
            'segments': [{
                'position': s['position'],
                'size': s['size'],
                'transcribed': bool((s['transcript'] or '').strip()),
                'url': f"/api/meeting/audio-sessions/{session_id}/segments/{s['position']}/audio",
            } for s in segments],
        })

