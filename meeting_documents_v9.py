import html
import io
import json
import os
import re
import textwrap
import zipfile
from datetime import datetime

import requests
from flask import request, jsonify, Response, abort
from sqlalchemy import text
from werkzeug.utils import secure_filename


MIGRATION_MARKER = 'move-reputacao-material-to-transformacao-v1'


def _response_text(payload):
    for item in payload.get('output', []) or []:
        if item.get('type') != 'message':
            continue
        for part in item.get('content', []) or []:
            if part.get('type') == 'output_text' and part.get('text'):
                return part['text']
    return ''


def _clean_json_text(value):
    value = (value or '').strip()
    if value.startswith('~~~'):
        value = re.sub(r'^~~~(?:json)?\s*', '', value, flags=re.I)
        value = re.sub(r'\s*~~~$', '', value)
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*', '', value, flags=re.I)
        value = re.sub(r'\s*```$', '', value)
    return value.strip()


def register(app_module):
    app = app_module.app
    db = app_module.db

    class ProjectAttachment(db.Model):
        __tablename__ = 'kaz_project_attachments'
        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.String(100), nullable=False, index=True)
        name = db.Column(db.String(255), nullable=False)
        mime_type = db.Column(db.String(160), nullable=False, default='application/octet-stream')
        size = db.Column(db.Integer, nullable=False, default=0)
        file_data = db.Column(db.LargeBinary, nullable=False)
        uploaded_by = db.Column(db.String(160), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def _state_locked():
        return db.session.execute(
            app_module.select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
        ).scalar_one()

    def _saved_meeting(payload, session_id, project_id=None):
        return next((
            item for item in (payload.get('meetings') or [])
            if (item.get('audioSessionId') or '') == session_id
            and (not project_id or item.get('projectId') == project_id)
        ), None)

    def _normalize_ai_document(saved):
        saved = saved or {}
        doc = saved.get('aiDocument')
        if not isinstance(doc, dict):
            doc = {}
        version = int(saved.get('aiDocumentVersion') or doc.get('version') or 0)

        key_points = []
        for item in (doc.get('keyPoints') or []):
            if isinstance(item, dict):
                text_value = str(item.get('text') or '').strip()
                if text_value:
                    key_points.append({
                        'type': item.get('type') if item.get('type') in ('decision', 'important') else 'important',
                        'text': text_value,
                    })
            elif str(item).strip():
                key_points.append({'type': 'important', 'text': str(item).strip()})

        suggested_actions = []
        source_actions = doc.get('suggestedActions')
        if source_actions is None:
            source_actions = doc.get('nextSteps') or []
        for item in (source_actions or []):
            if isinstance(item, dict):
                text_value = str(item.get('text') or '').strip()
            else:
                text_value = str(item or '').strip()
            if text_value:
                suggested_actions.append(text_value)

        attention = doc.get('attentionPoints') or []
        if isinstance(attention, str):
            attention = [line.strip(' -•\t') for line in attention.splitlines() if line.strip()]

        evolution = []
        for item in (doc.get('evolution') or []):
            if isinstance(item, dict):
                text_value = str(item.get('text') or '').strip()
                status = str(item.get('status') or '').strip()
                if text_value and status in ('completed', 'advanced', 'pending'):
                    evolution.append({'status': status, 'text': text_value})

        roadmap_impact = []
        for item in (doc.get('roadmapImpact') or []):
            if isinstance(item, dict):
                text_value = str(item.get('text') or '').strip()
                milestone_id = str(item.get('milestoneId') or '').strip()
                milestone_name = str(item.get('milestoneName') or '').strip()
                impact_type = str(item.get('impactType') or '').strip()
                if text_value and milestone_id and impact_type in ('advance', 'decision', 'pending', 'risk'):
                    roadmap_impact.append({
                        'milestoneId': milestone_id,
                        'milestoneName': milestone_name,
                        'impactType': impact_type,
                        'text': text_value,
                    })

        highlights = doc.get('executiveHighlights') or []
        if isinstance(highlights, str):
            highlights = [highlights]
        highlights = [str(item).strip() for item in highlights if str(item).strip()]

        if version >= 2 or any(key in doc for key in ('executiveSummary', 'keyPoints', 'suggestedActions', 'nextSteps', 'attentionPoints')):
            normalized_version = 4 if version >= 4 or 'suggestedActions' in doc or 'executiveHighlights' in doc else (3 if version >= 3 or evolution or roadmap_impact else 2)
            return {
                'version': normalized_version,
                'executiveSummary': str(doc.get('executiveSummary') or '').strip(),
                'executiveHighlights': highlights,
                'keyPoints': key_points,
                'suggestedActions': suggested_actions,
                'attentionPoints': [str(item).strip() for item in attention if str(item).strip()],
                'evolution': evolution,
                'roadmapImpact': roadmap_impact,
                'meetingSummary': str(doc.get('meetingSummary') or '').strip(),
            }

        legacy_summary = str(doc.get('summary') or saved.get('summary') or '').strip()
        legacy_points = doc.get('importantPoints') or []
        if isinstance(legacy_points, str):
            legacy_points = [line.strip(' -•\t') for line in legacy_points.splitlines() if line.strip()]
        return {
            'version': 1,
            'executiveSummary': legacy_summary,
            'executiveHighlights': [],
            'keyPoints': [{'type': 'important', 'text': str(item).strip()} for item in legacy_points if str(item).strip()],
            'suggestedActions': [],
            'attentionPoints': [],
            'evolution': [],
            'roadmapImpact': [],
            'meetingSummary': str(doc.get('meetingSummary') or legacy_summary).strip(),
        }

    def _previous_project_meeting(payload, project_id, current_session_id):
        meetings = [
            item for item in (payload.get('meetings') or [])
            if item.get('projectId') == project_id
            and (item.get('audioSessionId') or '') != current_session_id
        ]
        current = _saved_meeting(payload, current_session_id, project_id)
        current_at = (current or {}).get('at') or (current or {}).get('createdAt') or ''
        if current_at:
            meetings = [
                item for item in meetings
                if ((item.get('at') or item.get('createdAt') or '') < current_at)
            ]
        meetings.sort(key=lambda item: item.get('at') or item.get('createdAt') or '', reverse=True)
        return meetings[0] if meetings else None

    def _visible_project_ids(user, payload):
        if not user:
            return set()
        if user.role in ('admin', 'direction', 'viewer'):
            return {p.get('id') for p in (payload.get('projects') or [])}
        if user.project_id:
            return {user.project_id}
        return set()

    def _can_view_project(user, project_id, payload=None):
        if not user:
            return False
        if user.role in ('admin', 'direction', 'viewer'):
            return True
        return user.project_id == project_id

    def _sync_commitment(project, meeting, commitment, user):
        commitment = (commitment or '').strip()
        rows = project.setdefault('weeklyCommitments', [])
        source_id = meeting.get('id') or ''
        source_session = meeting.get('audioSessionId') or ''
        linked = next((
            item for item in rows
            if (source_id and item.get('sourceMeetingId') == source_id)
            or (source_session and item.get('sourceAudioSessionId') == source_session)
        ), None)
        if not commitment:
            if linked:
                rows.remove(linked)
            return
        if linked:
            linked['text'] = commitment
            linked['updatedAt'] = app_module.now_iso()
            linked['author'] = user.display_name
            if linked.get('status') not in ('Aberto', 'Parcial', 'Realizado', 'Não realizado'):
                linked['status'] = 'Aberto'
            return
        rows.append({
            'id': os.urandom(6).hex(),
            'text': commitment,
            'status': 'Aberto',
            'author': user.display_name,
            'createdAt': app_module.now_iso(),
            'source': 'meeting',
            'sourceMeetingId': source_id,
            'sourceAudioSessionId': source_session,
        })

    def _extract_attachment_text(name, mime_type, raw):
        if not raw:
            return ''
        lower = (name or '').lower()
        mime = (mime_type or '').lower()
        try:
            if lower.endswith('.pdf') or mime == 'application/pdf':
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw))
                return '\n'.join((page.extract_text() or '') for page in reader.pages)
            if lower.endswith(('.docx', '.pptx', '.xlsx')):
                chunks = []
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    names = archive.namelist()
                    if lower.endswith('.docx'):
                        wanted = [n for n in names if n == 'word/document.xml' or n.startswith('word/header') or n.startswith('word/footer')]
                    elif lower.endswith('.pptx'):
                        wanted = [n for n in names if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
                    else:
                        wanted = [n for n in names if n == 'xl/sharedStrings.xml' or (n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))]
                    for part in wanted:
                        value = archive.read(part).decode('utf-8', errors='ignore')
                        value = re.sub(r'<[^>]+>', ' ', value)
                        value = re.sub(r'\s+', ' ', value).strip()
                        if value:
                            chunks.append(value)
                return '\n'.join(chunks)
            if mime.startswith('text/') or lower.endswith(('.txt', '.csv', '.md', '.json')):
                return raw.decode('utf-8', errors='ignore')
        except Exception:
            app.logger.exception('Falha ao extrair texto do arquivo %s', name)
        return ''

    def _backup_personal_project(project):
        milestones = app_module.PersonalMilestone.query.filter_by(project_id=project.id).order_by(app_module.PersonalMilestone.position).all()
        journals = app_module.PersonalJournal.query.filter_by(project_id=project.id).order_by(app_module.PersonalJournal.created_at).all()
        tasks = app_module.PersonalTask.query.filter_by(project_id=project.id).order_by(app_module.PersonalTask.created_at).all()
        return {
            'project': {
                'id': project.id,
                'name': project.name,
                'owner_user_id': project.owner_user_id,
                'owner_name': project.owner_name,
                'responsible_user_id': project.responsible_user_id,
                'responsible_name': project.responsible_name,
                'visibility': project.visibility,
                'phase': project.phase,
                'health': project.health,
                'status': project.status,
                'objective': project.objective,
                'current_state': project.current_state,
                'last_advance': project.last_advance,
                'next_step': project.next_step,
                'priority': project.priority,
                'deadline': project.deadline,
            },
            'milestones': [{
                'id': m.id, 'name': m.name, 'status': m.status, 'health': m.health,
                'deadline': m.deadline, 'notes': m.notes, 'conclusion': m.conclusion,
                'position': m.position, 'active': m.active,
            } for m in milestones],
            'journals': [{
                'title': j.title, 'body': j.body, 'next_step': j.next_step, 'author': j.author,
                'created_at': j.created_at.isoformat() if j.created_at else '',
            } for j in journals],
            'tasks': [{
                'id': t.id, 'title': t.title, 'status': t.status, 'priority': t.priority,
                'due': t.due, 'responsible_name': t.responsible_name,
            } for t in tasks],
        }

    def _transform_project(source, target_id, target_name, owner_name):
        milestones = app_module.PersonalMilestone.query.filter_by(
            project_id=source.id, active=True
        ).order_by(app_module.PersonalMilestone.position).all()
        journals = app_module.PersonalJournal.query.filter_by(
            project_id=source.id
        ).order_by(app_module.PersonalJournal.created_at).all()
        now = app_module.now_iso()
        general_memos = []
        if (source.current_state or '').strip():
            general_memos.append({'at': now, 'author': 'Sistema', 'text': 'Contexto inicial: ' + source.current_state.strip()})
        for journal in journals:
            text_value = (journal.body or '').strip()
            if text_value:
                general_memos.append({
                    'at': journal.created_at.isoformat() if journal.created_at else now,
                    'author': journal.author or 'Sistema',
                    'text': f'{journal.title}: {text_value}',
                })
        mapped_milestones = []
        for pos, milestone in enumerate(milestones, 1):
            memos = []
            if (milestone.notes or '').strip():
                memos.append({'at': now, 'author': 'Sistema', 'text': milestone.notes.strip()})
            mapped_milestones.append({
                'id': f'{target_id}-m{pos}',
                'name': milestone.name,
                'status': milestone.status if milestone.status in ('Não iniciado','Em andamento','Em risco','Concluído') else 'Não iniciado',
                'deadline': milestone.deadline or '',
                'conclusion': milestone.conclusion or '',
                'memos': memos,
                'createdAt': now,
                'createdBy': 'Sistema',
            })
        return {
            'id': target_id,
            'name': target_name,
            'owner': owner_name,
            'status': source.status if source.status in ('Não iniciado','Em andamento','Em risco','Concluído') else 'Não iniciado',
            'objective': source.objective or '',
            'validated': False,
            'scopeDefined': False,
            'milestonesLocked': False,
            'milestonesLockedAt': '',
            'milestonesLockedBy': '',
            'milestones': mapped_milestones,
            'weeklyCommitments': [],
            'generalMemos': general_memos,
            'history': [{
                'at': now,
                'author': 'Sistema',
                'text': 'Projeto migrado de Minha Gestão para Transformação KAZ, preservando objetivo, contexto e Roadmap do Sucesso.',
            }],
            'files': [],
            'lastUpdate': now,
        }

    def _migrate_projects_once():
        if app_module.MigrationBackup.query.filter_by(backup_key=MIGRATION_MARKER).first():
            return
        source_specs = [
            ('my-kaz-reputacao-360', 'reputacao-kaz', 'Reputação KAZ', 'lais'),
            ('my-material-institucional', 'material-institucional', 'Material institucional', 'felippe'),
        ]
        state = _state_locked()
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        existing_ids = {p.get('id') for p in (payload.get('projects') or [])}
        snapshot = {'state_revision': state.revision, 'sources': [], 'users': []}
        changed = False
        for source_id, target_id, target_name, username in source_specs:
            source = db.session.get(app_module.PersonalProject, source_id)
            user = app_module.User.query.filter_by(username=username, active=True).first()
            if not user:
                raise RuntimeError(f'Usuário {username} não encontrado para migração.')
            snapshot['users'].append({
                'id': user.id, 'username': user.username, 'display_name': user.display_name,
                'role': user.role, 'project_id': user.project_id,
            })
            if source:
                snapshot['sources'].append(_backup_personal_project(source))
            if target_id not in existing_ids:
                if not source:
                    raise RuntimeError(f'Projeto de origem {source_id} não encontrado.')
                payload.setdefault('projects', []).append(_transform_project(source, target_id, target_name, user.display_name))
                existing_ids.add(target_id)
                changed = True
            user.role = 'owner'
            user.project_id = target_id
            if source:
                db.session.delete(source)
                changed = True

        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        db.session.add(app_module.MigrationBackup(
            backup_key=MIGRATION_MARKER,
            payload=snapshot,
            checksum=__import__('hashlib').sha256(raw).hexdigest(),
        ))
        if changed:
            state.payload = payload
            state.revision = int(state.revision or 0) + 1
            state.updated_by = 'Sistema · migração para Transformação KAZ'
            state.updated_at = datetime.utcnow()
        db.session.commit()

    def _project_or_404(payload, project_id):
        project = app_module.find_project(payload, project_id)
        if not project:
            abort(404)
        return project

    def _document_payload(item):
        return {
            'id': item.id,
            'name': item.name,
            'mimeType': item.mime_type,
            'size': item.size,
            'uploadedBy': item.uploaded_by,
            'createdAt': item.created_at.isoformat() if item.created_at else '',
            'url': f'/api/project-documents/{item.id}/download',
        }

    @app.route('/api/projects/<project_id>/documents', methods=['GET', 'POST'])
    @app_module.login_required
    def project_documents(project_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        project = _project_or_404(payload, project_id)
        if not _can_view_project(user, project_id, payload):
            abort(403)

        if request.method == 'POST':
            app_module.require_csrf()
            if not app_module.can_edit_project(user, project_id):
                abort(403)
            file_obj = request.files.get('file')
            if not file_obj or not file_obj.filename:
                return jsonify({'error': 'Selecione um arquivo.'}), 400
            raw = file_obj.read()
            if not raw:
                return jsonify({'error': 'Arquivo vazio.'}), 400
            if len(raw) > 20 * 1024 * 1024:
                return jsonify({'error': 'O arquivo excede 20 MB.'}), 413
            item = ProjectAttachment(
                project_id=project_id,
                name=secure_filename(file_obj.filename) or 'arquivo',
                mime_type=file_obj.mimetype or 'application/octet-stream',
                size=len(raw),
                file_data=raw,
                uploaded_by=user.display_name,
            )
            db.session.add(item)
            db.session.commit()

        direct = ProjectAttachment.query.filter_by(project_id=project_id).order_by(
            ProjectAttachment.created_at.desc(), ProjectAttachment.id.desc()
        ).all()

        roadmap_rows = db.session.execute(text("""
            SELECT id, milestone_id, name, mime_type, size, uploaded_by, created_at
              FROM kaz_attachments
             WHERE project_id=:project_id
               AND milestone_id IS NOT NULL
             ORDER BY created_at DESC NULLS LAST, id DESC
        """), {'project_id': project_id}).mappings().all()
        milestone_names = {str(m.get('id')): m.get('name') or '' for m in (project.get('milestones') or [])}

        meeting_rows = db.session.execute(text("""
            SELECT a.id, a.session_id, a.name, a.mime_type, a.size, a.uploaded_by, a.created_at,
                   s.started_at
              FROM kaz_meeting_attachments a
              LEFT JOIN kaz_meeting_audio_sessions s ON s.id=a.session_id
             WHERE a.project_id=:project_id
             ORDER BY a.created_at DESC NULLS LAST, a.id DESC
        """), {'project_id': project_id}).mappings().all()

        return jsonify({
            'canUpload': bool(app_module.can_edit_project(user, project_id)),
            'project': [_document_payload(item) for item in direct],
            'roadmap': [{
                'id': row['id'],
                'name': row['name'],
                'mimeType': row['mime_type'] or 'application/octet-stream',
                'size': row['size'] or 0,
                'uploadedBy': row['uploaded_by'] or '',
                'createdAt': row['created_at'].isoformat() if row['created_at'] else '',
                'milestoneId': row['milestone_id'],
                'milestoneName': milestone_names.get(str(row['milestone_id']), 'Roadmap do Sucesso'),
                'url': f"/api/milestone-attachments/{row['id']}/download",
            } for row in roadmap_rows],
            'meetings': [{
                'id': row['id'],
                'name': row['name'],
                'mimeType': row['mime_type'] or 'application/octet-stream',
                'size': row['size'] or 0,
                'uploadedBy': row['uploaded_by'] or '',
                'createdAt': row['created_at'].isoformat() if row['created_at'] else '',
                'sessionId': row['session_id'],
                'meetingDate': row['started_at'].isoformat() if row['started_at'] else '',
                'url': f"/api/meeting/attachments/{row['id']}/download",
            } for row in meeting_rows],
        })

    @app.route('/api/project-documents/<int:attachment_id>/download')
    @app_module.login_required
    def download_project_document(attachment_id):
        item = db.session.get(ProjectAttachment, attachment_id)
        if not item:
            abort(404)
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        if not _can_view_project(app_module.current_user(), item.project_id, payload):
            abort(403)
        disposition = 'attachment' if request.args.get('download') == '1' else 'inline'
        return Response(
            item.file_data,
            mimetype=item.mime_type or 'application/octet-stream',
            headers={'Content-Disposition': f'{disposition}; filename="{item.name}"'},
        )

    @app_module.login_required
    def meeting_history_list_v9():
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        names = {p.get('id'): p.get('name') or p.get('id') for p in (payload.get('projects') or [])}
        project_map = {p.get('id'): p for p in (payload.get('projects') or [])}
        visible_ids = _visible_project_ids(user, payload)
        if not visible_ids:
            return jsonify({'meetings': []})
        rows = db.session.execute(text("""
            SELECT s.id, s.project_id, s.created_by, s.status, s.started_at, s.ended_at,
                   COUNT(DISTINCT g.id) AS segment_count,
                   COUNT(DISTINCT a.id) AS attachment_count
              FROM kaz_meeting_audio_sessions s
              LEFT JOIN kaz_meeting_audio_segments g ON g.session_id=s.id
              LEFT JOIN kaz_meeting_attachments a ON a.session_id=s.id
             WHERE s.project_id = ANY(:project_ids)
             GROUP BY s.id, s.project_id, s.created_by, s.status, s.started_at, s.ended_at
             ORDER BY s.started_at DESC
        """), {'project_ids': list(visible_ids)}).mappings().all()
        meetings = []
        for row in rows:
            saved = _saved_meeting(payload, row['id'], row['project_id'])
            duration = None
            if row['segment_count'] and row['started_at']:
                end = row['ended_at'] or datetime.utcnow()
                duration = max(0, int((end - row['started_at']).total_seconds()))
            complete = int(row['attachment_count'] or 0) > 0
            meetings.append({
                'id': row['id'],
                'date': row['started_at'].isoformat() if row['started_at'] else '',
                'projectId': row['project_id'],
                'projectName': names.get(row['project_id'], row['project_id']),
                'createdBy': row['created_by'],
                'durationSeconds': duration,
                'hasAudio': bool(row['segment_count']),
                'registered': bool(saved),
                'attachmentCount': int(row['attachment_count'] or 0),
                'meetingStatus': 'Reunião completa' if complete else 'Reunião finalizada',
                'aiProcessed': bool(saved and saved.get('aiProcessed')),
                'aiProcessedAt': (saved or {}).get('aiProcessedAt') or '',
            })
        return jsonify({'meetings': meetings})

    @app_module.login_required
    def meeting_history_detail_v9(session_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        names = {p.get('id'): p.get('name') or p.get('id') for p in (payload.get('projects') or [])}
        project_map = {p.get('id'): p for p in (payload.get('projects') or [])}
        visible_ids = _visible_project_ids(user, payload)
        row = db.session.execute(text("""
            SELECT id, project_id, created_by, status, started_at, ended_at
              FROM kaz_meeting_audio_sessions
             WHERE id=:session_id
        """), {'session_id': session_id}).mappings().first()
        if not row:
            return jsonify({'error': 'Reunião não encontrada.'}), 404
        if row['project_id'] not in visible_ids:
            return jsonify({'error': 'Sem permissão para consultar esta reunião.'}), 403

        segments = db.session.execute(text("""
            SELECT position, size, transcript
              FROM kaz_meeting_audio_segments
             WHERE session_id=:session_id
             ORDER BY position
        """), {'session_id': session_id}).mappings().all()
        attachments = db.session.execute(text("""
            SELECT id, name, mime_type, size, uploaded_by, created_at
              FROM kaz_meeting_attachments
             WHERE session_id=:session_id
             ORDER BY created_at ASC, id ASC
        """), {'session_id': session_id}).mappings().all()
        saved = _saved_meeting(payload, session_id, row['project_id'])

        transcript = ((saved or {}).get('transcript') or '').strip()
        if not transcript:
            transcript = '\n\n'.join((s['transcript'] or '').strip() for s in segments if (s['transcript'] or '').strip())

        ai_document = _normalize_ai_document(saved)

        duration = 0
        if row['started_at']:
            duration = max(0, int(((row['ended_at'] or datetime.utcnow()) - row['started_at']).total_seconds()))

        return jsonify({
            'id': row['id'],
            'date': row['started_at'].isoformat() if row['started_at'] else '',
            'projectId': row['project_id'],
            'projectName': names.get(row['project_id'], row['project_id']),
            'projectOwner': (project_map.get(row['project_id']) or {}).get('owner') or '',
            'createdBy': row['created_by'],
            'durationSeconds': duration,
            'registered': bool(saved),
            'meetingStatus': 'Reunião completa' if attachments else 'Reunião finalizada',
            'attachmentCount': len(attachments),
            'canUploadAttachment': bool(app_module.can_edit_project(user, row['project_id'])),
            'canEditCommitment': bool(user and user.username == 'rachid'),
            'canGenerateAi': bool(user and user.username == 'rachid'),
            'transcript': transcript,
            'review': {
                'commitment': (saved or {}).get('nextWeek') or '',
                'aiProcessed': bool((saved or {}).get('aiProcessed')),
                'aiProcessedAt': (saved or {}).get('aiProcessedAt') or '',
                'aiSummaryStatus': (saved or {}).get('aiSummaryStatus') or ('success' if (saved or {}).get('aiProcessed') else ''),
                'aiDocumentVersion': ai_document.get('version') or 1,
                'isLegacyAiDocument': bool((saved or {}).get('aiProcessed') and (ai_document.get('version') or 1) < 4),
            },
            'aiDocument': ai_document,
            'pdfUrl': f'/api/meeting/history/{session_id}/pdf',
            'attachments': [{
                'id': a['id'],
                'name': a['name'],
                'mimeType': a['mime_type'],
                'size': a['size'],
                'uploadedBy': a['uploaded_by'],
                'createdAt': a['created_at'].isoformat() if a['created_at'] else '',
                'url': f"/api/meeting/attachments/{a['id']}/download",
            } for a in attachments],
            'segments': [{
                'position': s['position'],
                'size': s['size'],
                'transcribed': bool((s['transcript'] or '').strip()),
                'transcript': s['transcript'] or '',
                'url': f"/api/meeting/audio-sessions/{session_id}/segments/{s['position']}/audio",
            } for s in segments],
        })

    @app_module.login_required
    def update_meeting_commitment_v9(session_id):
        app_module.require_csrf()
        user = app_module.current_user()
        if not user or user.username != 'rachid':
            return jsonify({'error': 'A partir do encerramento da reunião, somente Rachid pode alterar o compromisso da próxima reunião.'}), 403
        session = db.session.execute(text("""
            SELECT id, project_id FROM kaz_meeting_audio_sessions WHERE id=:session_id
        """), {'session_id': session_id}).mappings().first()
        if not session:
            return jsonify({'error': 'Reunião não encontrada.'}), 404
        body = request.get_json(force=True) or {}
        state = _state_locked()
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        project = app_module.find_project(payload, session['project_id'])
        meeting = _saved_meeting(payload, session_id, session['project_id'])
        if not project or not meeting:
            return jsonify({'error': 'Reunião salva não encontrada.'}), 404
        commitment = (body.get('commitment') or '').strip()
        meeting['nextWeek'] = commitment
        meeting['commitmentUpdatedAt'] = app_module.now_iso()
        meeting['commitmentUpdatedBy'] = user.display_name
        _sync_commitment(project, meeting, commitment, user)
        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'commitment': commitment, 'revision': state.revision})

    @app_module.login_required
    def summarize_meeting_v9():
        app_module.require_csrf()
        body = request.get_json(force=True) or {}
        project_id = (body.get('projectId') or '').strip()
        session_id = (body.get('sessionId') or '').strip()
        transcript = (body.get('transcript') or '').strip()
        user = app_module.current_user()
        if not project_id or not user or user.username != 'rachid':
            abort(403)

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            return jsonify({'configured': False, 'error': 'A IA de reunião ainda não possui credencial configurada no servidor.'}), 503

        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        project = _project_or_404(payload, project_id)
        meeting = _saved_meeting(payload, session_id, project_id) if session_id else None
        if session_id and not meeting:
            return jsonify({'error': 'Salve a reunião antes de gerar o resumo.'}), 409

        if not transcript and session_id:
            rows = db.session.execute(text("""
                SELECT transcript FROM kaz_meeting_audio_segments
                 WHERE session_id=:session_id ORDER BY position
            """), {'session_id': session_id}).mappings().all()
            transcript = '\n\n'.join((row['transcript'] or '').strip() for row in rows if (row['transcript'] or '').strip())

        if not transcript:
            return jsonify({'error': 'A reunião ainda não possui transcrição suficiente para gerar o resumo.'}), 400

        docs = []
        if session_id:
            rows = db.session.execute(text("""
                SELECT name, mime_type, file_data
                  FROM kaz_meeting_attachments
                 WHERE session_id=:session_id
                 ORDER BY id
                 LIMIT 10
            """), {'session_id': session_id}).mappings().all()
            remaining = 80000
            for row in rows:
                extracted = _extract_attachment_text(row['name'], row['mime_type'], row['file_data']).strip()
                if not extracted:
                    continue
                extracted = extracted[:remaining]
                if not extracted:
                    break
                docs.append(f"ARQUIVO: {row['name']}\n{extracted}")
                remaining -= len(extracted)
                if remaining <= 0:
                    break

        commitment = ((meeting or {}).get('nextWeek') or '').strip()
        previous = _previous_project_meeting(payload, project_id, session_id)
        previous_context = 'Esta é a primeira reunião disponível deste projeto. Retorne evolution=[] sem tentar inferir histórico.'
        if previous:
            prev_doc = _normalize_ai_document(previous)
            previous_context = f"""REUNIÃO ANTERIOR DO MESMO PROJETO:
Data: {previous.get('at') or previous.get('createdAt') or 'não informada'}
Compromisso registrado: {previous.get('nextWeek') or 'não informado'}
Resumo executivo anterior: {prev_doc.get('executiveSummary') or previous.get('summary') or 'não disponível'}
Ações sugeridas anteriores: {json.dumps(prev_doc.get('suggestedActions') or [], ensure_ascii=False)}
Pontos de atenção anteriores: {json.dumps(prev_doc.get('attentionPoints') or [], ensure_ascii=False)}
Contexto capturado antes da reunião anterior: {json.dumps(previous.get('previousReview') or {}, ensure_ascii=False)}

Use esse histórico SOMENTE para o bloco evolution. Uma evolução só pode ser classificada como completed ou advanced quando houver evidência suficiente na reunião atual. Se algo importante continuar sem resolução, pode ser pending."""

        milestones = project.get('milestones') or []
        roadmap_context = []
        valid_milestone_ids = set()
        milestone_name_by_id = {}
        for milestone in milestones[:40]:
            milestone_id = str(milestone.get('id') or '').strip()
            if not milestone_id:
                continue
            valid_milestone_ids.add(milestone_id)
            milestone_name_by_id[milestone_id] = milestone.get('name') or milestone_id
            notes = []
            if milestone.get('conclusion'):
                notes.append('conclusão: ' + str(milestone.get('conclusion')))
            memos = milestone.get('memos') or []
            if memos:
                last_memo = memos[-1]
                if isinstance(last_memo, dict) and last_memo.get('text'):
                    notes.append('último registro: ' + str(last_memo.get('text'))[:500])
            roadmap_context.append(
                f"- ID={milestone_id} | marco={milestone.get('name') or 'Marco'} | status={milestone.get('status') or '—'}"
                + (f" | {' | '.join(notes)}" if notes else '')
            )

        project_context = f"""OBJETIVO DO PROJETO:
{(project.get('objective') or 'Não informado.').strip()}

ROADMAP DO SUCESSO — MARCOS EXISTENTES:
{chr(10).join(roadmap_context) if roadmap_context else 'Não informado.'}

REGRAS DO ROADMAP:
- roadmapImpact só pode citar IDs presentes acima.
- Não crie, renomeie, conclua nem altere status de marco.
- O bloco apenas registra o efeito percebido desta reunião sobre um marco existente.
- Se não houver relação clara, retorne roadmapImpact=[].
"""

        model = os.environ.get('MEETING_SUMMARY_MODEL', 'gpt-5.6-luna')

        def compact_transcript_if_needed(raw_transcript):
            # Reuniões longas são condensadas em partes antes do registro final.
            # Se a compactação falhar, usamos a transcrição integral como fallback.
            if len(raw_transcript) <= 50000:
                return raw_transcript

            chunks = []
            cursor = 0
            chunk_size = 22000
            overlap = 800
            while cursor < len(raw_transcript):
                end = min(len(raw_transcript), cursor + chunk_size)
                piece = raw_transcript[cursor:end]
                chunks.append(piece)
                if end >= len(raw_transcript):
                    break
                cursor = max(end - overlap, cursor + 1)

            condensed = []
            for index, piece in enumerate(chunks, 1):
                compression_prompt = f"""Condense o trecho {index} de {len(chunks)} de uma reunião da Transformação KAZ.
Preserve fatos, números, decisões, pontos estratégicos, ações sugeridas, pendências, riscos, divergências e referências a marcos do projeto.
Remova repetições, vícios de fala e exemplos sem efeito gerencial.
Não invente informação. Não conclua o que não foi concluído.
Escreva em português, em texto corrido objetivo, sem JSON e sem markdown.

TRECHO:
{piece}
"""
                try:
                    compression_response = requests.post(
                        'https://api.openai.com/v1/responses',
                        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                        json={
                            'model': model,
                            'input': compression_prompt,
                            'max_output_tokens': 2200,
                        },
                        timeout=180,
                    )
                    if compression_response.status_code >= 400:
                        app.logger.warning('Falha ao condensar trecho %s/%s: %s', index, len(chunks), compression_response.text[:500])
                        return raw_transcript
                    piece_text = _response_text(compression_response.json()).strip()
                    if not piece_text:
                        return raw_transcript
                    condensed.append(f"TRECHO CONDENSADO {index}/{len(chunks)}:\n{piece_text}")
                except requests.RequestException:
                    app.logger.exception('Falha de comunicação ao condensar reunião longa.')
                    return raw_transcript

            return '\n\n'.join(condensed)

        transcript_for_ai = compact_transcript_if_needed(transcript)

        prompt = f"""Você produz o REGISTRO EXECUTIVO das reuniões da Transformação KAZ.

Sua função NÃO é transcrever a conversa e NÃO é simplesmente encurtar a transcrição. Você deve interpretar a reunião como um profissional de gestão e registrar apenas o que tem valor para acompanhamento executivo do projeto.

PROJETO: {project.get('name') or project_id}

PRINCÍPIOS OBRIGATÓRIOS:
1. A TRANSCRIÇÃO atual é a principal fonte de verdade.
2. Arquivos anexados, reunião anterior e contexto do projeto servem apenas para compreensão e comparação.
3. Elimine vícios de fala, repetições, interrupções, exemplos laterais, brincadeiras e conversas sem relevância.
4. Organize por importância executiva, não por ordem cronológica.
5. Diferencie discussão, decisão, ação sugerida e ponto de atenção.
6. Nunca transforme hipótese, sugestão, pergunta ou comentário em decisão.
7. Nunca invente número, decisão, evolução, impacto ou conclusão.
8. Use linguagem executiva, direta, profissional e natural.
9. O compromisso oficial da próxima reunião é campo do sistema. NÃO crie, altere ou deduza esse compromisso.
10. Não mencione transcrição, áudio, prompt, IA ou processo de geração.
11. Não use markdown. Responda SOMENTE JSON válido.

BLOCOS:

executiveSummary:
- 80 a 130 palavras no total;
- separar em 2 ou 3 parágrafos curtos, usando duas quebras de linha entre parágrafos;
- foco, avanços/definições e situação do projeto ao final;
- não repetir todos os bullets.

executiveHighlights:
- 2 a 4 frases curtas ou expressões IMPORTANTES copiadas exatamente do executiveSummary;
- servem apenas para destaque visual em negrito;
- não invente texto novo.

evolution:
- SOMENTE comparação com a reunião anterior fornecida;
- use status "completed" quando algo previamente assumido/pendente foi efetivamente concluído;
- use "advanced" quando houve avanço concreto, decisão ou evolução;
- use "pending" quando algo relevante continua sem solução;
- se não houver reunião anterior, retorne [];
- não invente evolução.

keyPoints:
- decisões e informações estratégicas;
- type = "decision" ou "important";
- em geral 3 a 8 itens.

suggestedActions:
- somente ações sugeridas ou encaminhamentos decorrentes da reunião;
- retorne apenas o texto da ação;
- NÃO atribua responsável;
- NÃO crie prazo;
- NÃO duplique o compromisso oficial da próxima reunião apenas porque ele aparece abaixo.

attentionPoints:
- somente risco, dependência, bloqueio, atraso, divergência ou falta de definição relevante;
- [] quando não houver.

roadmapImpact:
- relacione apenas marcos existentes do Roadmap;
- cada item: milestoneId, milestoneName, impactType e text;
- impactType: "advance", "decision", "pending" ou "risk";
- NÃO altera o Roadmap; apenas descreve o impacto da reunião;
- se a relação não for clara, não inclua.

meetingSummary:
- 3 a 6 parágrafos curtos;
- contexto, raciocínio, assuntos centrais, decisões e encaminhamentos;
- síntese executiva, não ata.

FORMATO EXATO:
{{
  "executiveSummary": "parágrafo 1\\n\\nparágrafo 2",
  "executiveHighlights": ["frase exata do resumo", "outra frase exata"],
  "evolution": [
    {{"status": "completed", "text": "texto"}},
    {{"status": "advanced", "text": "texto"}},
    {{"status": "pending", "text": "texto"}}
  ],
  "keyPoints": [
    {{"type": "decision", "text": "texto"}},
    {{"type": "important", "text": "texto"}}
  ],
  "suggestedActions": ["ação sugerida"],
  "attentionPoints": ["texto"],
  "roadmapImpact": [
    {{"milestoneId": "ID exato", "milestoneName": "nome exato", "impactType": "advance", "text": "texto"}}
  ],
  "meetingSummary": "texto com parágrafos separados por duas quebras de linha"
}}

{project_context}

{previous_context}

COMPROMISSO OFICIAL DA PRÓXIMA REUNIÃO — NÃO ALTERAR NEM DEDUZIR:
{commitment or 'Não informado.'}

TRANSCRIÇÃO DA REUNIÃO ATUAL:
{transcript_for_ai}

ARQUIVOS ANEXADOS — APENAS CONTEXTO COMPLEMENTAR:
{'\n\n'.join(docs) if docs else 'Nenhum arquivo com conteúdo textual extraível.'}
"""
        try:
            response_schema = {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'executiveSummary': {'type': 'string'},
                    'executiveHighlights': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'evolution': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'properties': {
                                'status': {'type': 'string', 'enum': ['completed', 'advanced', 'pending']},
                                'text': {'type': 'string'},
                            },
                            'required': ['status', 'text'],
                        },
                    },
                    'keyPoints': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'properties': {
                                'type': {'type': 'string', 'enum': ['decision', 'important']},
                                'text': {'type': 'string'},
                            },
                            'required': ['type', 'text'],
                        },
                    },
                    'suggestedActions': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'attentionPoints': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'roadmapImpact': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'properties': {
                                'milestoneId': {'type': 'string'},
                                'milestoneName': {'type': 'string'},
                                'impactType': {'type': 'string', 'enum': ['advance', 'decision', 'pending', 'risk']},
                                'text': {'type': 'string'},
                            },
                            'required': ['milestoneId', 'milestoneName', 'impactType', 'text'],
                        },
                    },
                    'meetingSummary': {'type': 'string'},
                },
                'required': [
                    'executiveSummary',
                    'executiveHighlights',
                    'evolution',
                    'keyPoints',
                    'suggestedActions',
                    'attentionPoints',
                    'roadmapImpact',
                    'meetingSummary',
                ],
            }

            request_payload = {
                'model': model,
                'input': prompt,
                'max_output_tokens': 7000,
                'text': {
                    'format': {
                        'type': 'json_schema',
                        'name': 'kaz_meeting_executive_record_v4',
                        'description': 'Registro executivo estruturado de uma reunião da Transformação KAZ.',
                        'schema': response_schema,
                        'strict': True,
                    }
                },
            }

            response = requests.post(
                'https://api.openai.com/v1/responses',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json=request_payload,
                timeout=240,
            )

            if response.status_code == 400:
                app.logger.warning('Structured Outputs recusado pelo modelo %s; usando JSON mode. %s', model, response.text[:500])
                fallback_payload = {
                    'model': model,
                    'input': prompt,
                    'max_output_tokens': 7000,
                    'text': {'format': {'type': 'json_object'}},
                }
                response = requests.post(
                    'https://api.openai.com/v1/responses',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json=fallback_payload,
                    timeout=240,
                )

            if response.status_code >= 400:
                app.logger.error('Falha no resumo IA executivo V4: %s', response.text[:1000])
                return jsonify({'error': 'A gravação foi preservada, mas a IA não conseguiu processar o registro executivo.'}), 502

            response_payload = response.json()
            if response_payload.get('status') == 'incomplete':
                app.logger.error('Resposta IA V4 incompleta: %s', json.dumps(response_payload.get('incomplete_details') or {}, ensure_ascii=False))
                return jsonify({'error': 'A IA não concluiu o registro executivo. Tente reprocessar novamente.'}), 502

            raw_text = _clean_json_text(_response_text(response_payload))
            try:
                structured = json.loads(raw_text)
            except Exception:
                app.logger.error('Resposta IA V4 não era JSON válido: %s', raw_text[:1500])
                return jsonify({'error': 'A IA respondeu, mas o registro executivo não veio no formato esperado. Tente reprocessar.'}), 502

            executive_summary = str(structured.get('executiveSummary') or '').strip()
            executive_highlights = [str(item).strip() for item in (structured.get('executiveHighlights') or []) if str(item).strip()]
            meeting_summary = str(structured.get('meetingSummary') or '').strip()

            key_points = []
            for item in (structured.get('keyPoints') or []):
                if isinstance(item, dict):
                    value = str(item.get('text') or '').strip()
                    if value:
                        key_points.append({
                            'type': item.get('type') if item.get('type') in ('decision', 'important') else 'important',
                            'text': value,
                        })

            suggested_actions = []
            for item in (structured.get('suggestedActions') or []):
                value = str(item or '').strip()
                if value:
                    suggested_actions.append(value)

            attention = structured.get('attentionPoints') or []
            if isinstance(attention, str):
                attention = [line.strip(' -•\t') for line in attention.splitlines() if line.strip()]
            attention = [str(item).strip() for item in attention if str(item).strip()]

            evolution = []
            if previous:
                for item in (structured.get('evolution') or []):
                    if not isinstance(item, dict):
                        continue
                    value = str(item.get('text') or '').strip()
                    status = str(item.get('status') or '').strip()
                    if value and status in ('completed', 'advanced', 'pending'):
                        evolution.append({'status': status, 'text': value})

            roadmap_impact = []
            for item in (structured.get('roadmapImpact') or []):
                if not isinstance(item, dict):
                    continue
                milestone_id = str(item.get('milestoneId') or '').strip()
                impact_type = str(item.get('impactType') or '').strip()
                value = str(item.get('text') or '').strip()
                if milestone_id in valid_milestone_ids and impact_type in ('advance', 'decision', 'pending', 'risk') and value:
                    roadmap_impact.append({
                        'milestoneId': milestone_id,
                        'milestoneName': milestone_name_by_id.get(milestone_id, milestone_id),
                        'impactType': impact_type,
                        'text': value,
                    })

            if not executive_summary or not meeting_summary:
                return jsonify({'error': 'A IA não retornou conteúdo suficiente para o registro executivo.'}), 502

            document = {
                'version': 4,
                'executiveSummary': executive_summary,
                'executiveHighlights': executive_highlights,
                'evolution': evolution,
                'keyPoints': key_points,
                'suggestedActions': suggested_actions,
                'attentionPoints': attention,
                'roadmapImpact': roadmap_impact,
                'meetingSummary': meeting_summary,
            }

            state = _state_locked()
            payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
            saved = _saved_meeting(payload, session_id, project_id)
            if not saved:
                return jsonify({'error': 'Reunião salva não encontrada.'}), 404

            old_document = saved.get('aiDocument')
            if isinstance(old_document, dict) and old_document:
                history = saved.setdefault('aiDocumentHistory', [])
                history.append({
                    'document': old_document,
                    'version': int(saved.get('aiDocumentVersion') or old_document.get('version') or 1),
                    'processedAt': saved.get('aiProcessedAt') or '',
                    'processedBy': saved.get('aiProcessedBy') or '',
                    'preservedAt': app_module.now_iso(),
                })
                if len(history) > 5:
                    del history[:-5]

            saved['summary'] = executive_summary
            saved['aiDocument'] = document
            saved['aiDocumentVersion'] = 4
            saved['transcript'] = transcript
            saved['aiProcessed'] = True
            saved['aiSummaryStatus'] = 'success'
            saved['aiProcessedAt'] = app_module.now_iso()
            saved['aiProcessedBy'] = user.display_name
            state.payload = payload
            state.revision = int(state.revision or 0) + 1
            state.updated_by = user.display_name
            state.updated_at = datetime.utcnow()
            db.session.commit()

            return jsonify({
                'configured': True,
                'aiProcessed': True,
                'aiSummaryStatus': 'success',
                'aiDocumentVersion': 4,
                'document': document,
                'summary': executive_summary,
                'revision': state.revision,
            })
        except requests.RequestException:
            app.logger.exception('Falha de comunicação com IA da reunião V4')
            return jsonify({'error': 'Falha de comunicação com a IA da reunião.'}), 502

    @app.route('/api/projects/<project_id>/suggested-actions')
    @app_module.login_required
    def project_suggested_actions(project_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        _project_or_404(payload, project_id)
        if not _can_view_project(user, project_id, payload):
            abort(403)

        rows = []
        for meeting in (payload.get('meetings') or []):
            if meeting.get('projectId') != project_id or not meeting.get('aiProcessed'):
                continue
            document = _normalize_ai_document(meeting)
            actions = document.get('suggestedActions') or []
            if not actions:
                continue
            meeting_date = meeting.get('at') or meeting.get('createdAt') or ''
            session_id = meeting.get('audioSessionId') or ''
            for action in actions:
                value = str(action or '').strip()
                if value:
                    rows.append({
                        'text': value,
                        'meetingDate': meeting_date,
                        'sessionId': session_id,
                    })

        rows.sort(key=lambda item: item.get('meetingDate') or '', reverse=True)
        return jsonify({'items': rows, 'count': len(rows)})

    def _pdf_escape(value):
        raw = str(value or '').replace('\r', ' ').replace('\t', ' ')
        encoded = raw.encode('cp1252', errors='replace').decode('latin1')
        return encoded.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    def _native_meeting_pdf(project_name, date_text, owner_name, duration_text, meeting_status, document, commitment, attachments):
        width, height = 595.28, 841.89
        left, right, top, bottom = 44.0, 44.0, 42.0, 48.0
        content_width = width - left - right
        y = height - top
        pages = [[]]

        # Brandbook KAZ — aplicação executiva
        FUCHSIA = '#FF0084'
        BLACK = '#0A0C11'
        ICE = '#F4F4F4'
        WHITE = '#FFFFFF'
        TEXT = '#222630'
        MUTED = '#767C87'
        LINE = '#E4E4E6'
        SOFT_PINK = '#FFF0F7'
        GREEN = '#24765A'
        GREEN_SOFT = '#EAF7F1'
        AMBER = '#9A6514'
        AMBER_SOFT = '#FFF6E5'
        RED = '#A83A4A'
        RED_SOFT = '#FFF0F2'

        def rgb(hex_value):
            value = hex_value.lstrip('#')
            return tuple(int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4))

        def new_page():
            nonlocal y
            pages.append([])
            y = height - top

        def ensure_space(required):
            if y - required < bottom + 20:
                new_page()
                return True
            return False

        def rect(x, y0, w, h, fill=None, stroke=None, line_width=0.7):
            cmd = []
            if fill:
                r, g, b = rgb(fill)
                cmd.append(f'{r:.3f} {g:.3f} {b:.3f} rg')
            if stroke:
                r, g, b = rgb(stroke)
                cmd.append(f'{r:.3f} {g:.3f} {b:.3f} RG {line_width:.2f} w')
            op = 'B' if fill and stroke else ('f' if fill else 'S')
            cmd.append(f'{x:.2f} {y0:.2f} {w:.2f} {h:.2f} re {op}')
            pages[-1].append(' '.join(cmd))

        def line(x1, y1, x2, y2, color=LINE, line_width=0.6):
            r, g, b = rgb(color)
            pages[-1].append(f'{line_width:.2f} w {r:.3f} {g:.3f} {b:.3f} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S')

        def text_line(value, x, baseline, size=10, bold=False, color=TEXT):
            r, g, b = rgb(color)
            font = 'F2' if bold else 'F1'
            safe = _pdf_escape(value)
            pages[-1].append(
                f'BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {x:.2f} {baseline:.2f} Tm ({safe}) Tj ET'
            )

        def bolt(x, y0, scale=1.0, color=FUCHSIA):
            r, g, b = rgb(color)
            pts = [
                (x+7*scale, y0+25*scale),
                (x+18*scale, y0+25*scale),
                (x+13*scale, y0+15*scale),
                (x+22*scale, y0+15*scale),
                (x+5*scale, y0),
                (x+10*scale, y0+10*scale),
                (x+2*scale, y0+10*scale),
            ]
            cmd = [f'{r:.3f} {g:.3f} {b:.3f} rg']
            cmd.append(f'{pts[0][0]:.2f} {pts[0][1]:.2f} m')
            for px, py in pts[1:]:
                cmd.append(f'{px:.2f} {py:.2f} l')
            cmd.append('h f')
            pages[-1].append(' '.join(cmd))

        def wrapped(value, size=10, max_width=None):
            value = str(value or '').strip()
            if not value:
                return []
            max_width = max_width or content_width
            avg = max(size * 0.49, 4.2)
            max_chars = max(18, int(max_width / avg))
            result = []
            for paragraph in re.split(r'\n\s*\n|\n', value):
                paragraph = paragraph.strip()
                if not paragraph:
                    result.append('')
                    continue
                result.extend(textwrap.wrap(
                    paragraph,
                    width=max_chars,
                    break_long_words=False,
                    break_on_hyphens=False,
                    replace_whitespace=True,
                ) or [''])
            return result

        def section_title(title, subtitle=''):
            nonlocal y
            ensure_space(42)
            bolt(left, y-16, .55, FUCHSIA)
            text_line(title.upper(), left+18, y, 10.2, True, BLACK)
            y -= 16
            if subtitle:
                for row in wrapped(subtitle, 8.2, content_width-18):
                    text_line(row, left+18, y, 8.2, False, MUTED)
                    y -= 11
            y -= 5

        def paragraph_block(value, size=9.5):
            nonlocal y
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', str(value or '')) if p.strip()]
            for paragraph in paragraphs:
                rows = wrapped(paragraph, size, content_width)
                ensure_space(max(28, len(rows)*14 + 10))
                for row in rows:
                    text_line(row, left, y, size, False, TEXT)
                    y -= 14
                y -= 8

        def executive_card(body, highlights):
            nonlocal y
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', str(body or '')) if p.strip()]
            paragraph_rows = []
            total_rows = 0
            for paragraph in paragraphs or ['']:
                rows = wrapped(paragraph, 10.5, content_width-46)
                paragraph_rows.append(rows)
                total_rows += max(1, len(rows))
            extra_space = max(0, len(paragraph_rows)-1) * 8
            card_h = 40 + total_rows*15 + extra_space
            ensure_space(card_h+12)
            rect(left, y-card_h+6, content_width, card_h, ICE, LINE, 0.7)
            rect(left, y-card_h+6, 7, card_h, FUCHSIA, None)
            text_line('RESUMO EXECUTIVO', left+23, y-15, 8.6, True, FUCHSIA)
            baseline = y-38
            highlights_lower = [str(item).lower() for item in (highlights or []) if str(item).strip()]
            for p_index, rows in enumerate(paragraph_rows):
                for row in rows or ['']:
                    row_lower = row.lower()
                    is_highlight = any(h and h in row_lower for h in highlights_lower)
                    text_line(row, left+23, baseline, 10.5, is_highlight, BLACK)
                    baseline -= 15
                if p_index < len(paragraph_rows)-1:
                    baseline -= 8
            y -= card_h + 10

        def metrics_row():
            nonlocal y
            decisions = len([p for p in (document.get('keyPoints') or []) if p.get('type') == 'decision'])
            next_count = len(document.get('suggestedActions') or [])
            attention_count = len(document.get('attentionPoints') or [])
            docs_count = len(attachments or [])
            values = [
                (str(decisions), 'DECISÕES'),
                (str(next_count), 'AÇÕES'),
                (str(attention_count), 'ATENÇÕES'),
                (str(docs_count), 'DOCUMENTOS'),
            ]
            h = 52
            ensure_space(h+12)
            col = content_width/4
            for idx,(value,label) in enumerate(values):
                x = left + idx*col
                rect(x, y-h+5, col-(4 if idx<3 else 0), h, WHITE, LINE, 0.6)
                text_line(value, x+12, y-19, 18, True, FUCHSIA if idx==0 else BLACK)
                text_line(label, x+12, y-36, 6.6, True, MUTED)
            y -= h+13

        def evolution_block(items):
            nonlocal y
            if not items:
                return
            labels = {
                'completed': ('CONCLUÍDO', GREEN, GREEN_SOFT),
                'advanced': ('AVANÇOU', FUCHSIA, SOFT_PINK),
                'pending': ('PERMANECE PENDENTE', AMBER, AMBER_SOFT),
            }
            for item in items:
                label,color,bg = labels.get(item.get('status'), ('EVOLUÇÃO', BLACK, ICE))
                rows = wrapped(item.get('text') or '', 9.2, content_width-44)
                h = 30 + max(1,len(rows))*13
                ensure_space(h+6)
                rect(left, y-h+5, content_width, h, bg, None)
                text_line(label, left+14, y-13, 7.5, True, color)
                baseline = y-31
                for row in rows:
                    text_line(row,left+14,baseline,9.2,False,TEXT)
                    baseline -= 13
                y -= h+5

        def numbered_points(items):
            nonlocal y
            if not items:
                rect(left,y-27,content_width,31,ICE,LINE,0.6)
                text_line('Nenhuma decisão ou ponto estratégico adicional identificado.',left+12,y-15,8.8,False,MUTED)
                y -= 40
                return
            for idx,item in enumerate(items,1):
                rows = wrapped(item.get('text') or '', 9.5, content_width-92)
                h = 28 + max(1,len(rows))*13
                ensure_space(h+7)
                rect(left,y-h+5,content_width,h,WHITE,LINE,0.6)
                text_line(str(idx).zfill(2),left+13,y-18,14,True,FUCHSIA)
                label = 'DECISÃO' if item.get('type') == 'decision' else 'PONTO ESTRATÉGICO'
                text_line(label,left+54,y-12,7.2,True,GREEN if item.get('type')=='decision' else FUCHSIA)
                baseline=y-31
                for row in rows:
                    text_line(row,left+54,baseline,9.5,False,TEXT)
                    baseline -= 13
                y -= h+5

        def action_list(items):
            nonlocal y
            if not items:
                rect(left,y-27,content_width,31,ICE,LINE,0.6)
                text_line('Nenhuma ação sugerida foi identificada com segurança.',left+12,y-15,8.8,False,MUTED)
                y -= 40
                return
            for idx,item in enumerate(items,1):
                rows = wrapped(str(item or ''), 9.2, content_width-58)
                h = 24 + max(1,len(rows))*13
                ensure_space(h+4)
                rect(left,y-h+5,content_width,h,WHITE,LINE,0.55)
                text_line(str(idx).zfill(2),left+12,y-15,8.2,True,FUCHSIA)
                base=y-14
                for i,row in enumerate(rows):
                    text_line(row,left+44,base-i*13,9.2,False,TEXT)
                y -= h+3

        def attention_block(items):
            nonlocal y
            if not items:
                return
            total=0
            rows_by=[]
            for item in items:
                rows=wrapped(item,9.2,content_width-42)
                rows_by.append(rows); total += max(1,len(rows))
            h=28+total*13+len(items)*5
            ensure_space(h+8)
            rect(left,y-h+5,content_width,h,BLACK,None)
            text_line('ATENÇÃO',left+14,y-13,8.2,True,FUCHSIA)
            base=y-34
            for rows in rows_by:
                text_line('•',left+15,base,9.5,True,FUCHSIA)
                for i,row in enumerate(rows):
                    text_line(row,left+29,base-i*13,9.2,False,WHITE)
                base -= max(1,len(rows))*13+5
            y -= h+8

        def roadmap_block(items):
            nonlocal y
            labels = {
                'advance': ('AVANÇO', FUCHSIA),
                'decision': ('DECISÃO', GREEN),
                'pending': ('PENDÊNCIA', AMBER),
                'risk': ('RISCO', RED),
            }
            if not items:
                rect(left,y-27,content_width,31,ICE,LINE,0.6)
                text_line('Nenhum impacto claro no Roadmap do Sucesso foi identificado.',left+12,y-15,8.8,False,MUTED)
                y -= 40
                return
            for item in items:
                label,color=labels.get(item.get('impactType'),('IMPACTO',BLACK))
                title_rows=wrapped(item.get('milestoneName') or 'Marco',9.3,content_width-145)
                body_rows=wrapped(item.get('text') or '',8.8,content_width-34)
                h=34+len(title_rows)*12+len(body_rows)*12
                ensure_space(h+5)
                rect(left,y-h+5,content_width,h,ICE,None)
                text_line(label,left+14,y-13,7.4,True,color)
                for i,row in enumerate(title_rows):
                    text_line(row,left+80,y-13-i*12,9.3,True,BLACK)
                base=y-30-len(title_rows)*12
                for i,row in enumerate(body_rows):
                    text_line(row,left+14,base-i*12,8.8,False,TEXT)
                y -= h+5

        def commitment_card(value):
            nonlocal y
            if not value:
                return
            rows=wrapped(value,10.2,content_width-50)
            h=38+len(rows)*15
            ensure_space(h+10)
            rect(left,y-h+5,content_width,h,FUCHSIA,None)
            bolt(left+14,y-31,.55,WHITE)
            text_line('PRÓXIMO MARCO',left+34,y-14,8.2,True,WHITE)
            base=y-38
            for row in rows:
                text_line(row,left+18,base,10.2,True,WHITE)
                base -= 15
            y -= h+10

        def attachments_block(items):
            nonlocal y
            if not items:
                return
            for idx,item in enumerate(items,1):
                rows=wrapped(item.get('name') or 'Arquivo',8.8,content_width-100)
                h=max(30,15+len(rows)*11)
                ensure_space(h+3)
                rect(left,y-h+5,content_width,h,ICE,None)
                text_line(str(idx).zfill(2),left+12,y-14,8.5,True,FUCHSIA)
                for i,row in enumerate(rows):
                    text_line(row,left+47,y-12-i*11,8.8,True,BLACK)
                meta=item.get('meta') or ''
                if meta:
                    text_line(meta,left+47,y-h+13,7.4,False,MUTED)
                y -= h+3

        # Capa/cabeçalho no espírito do brandbook: preto + fúcsia + tipografia de impacto.
        header_h=148
        rect(0,height-header_h,width,header_h,BLACK,None)
        rect(0,height-header_h,11,header_h,FUCHSIA,None)
        bolt(left,height-52,.95,FUCHSIA)
        text_line('TRANSFORMAÇÃO KAZ',left+30,height-32,8.2,True,WHITE)
        text_line('REGISTRO EXECUTIVO',left+30,height-47,7.2,True,FUCHSIA)
        title_rows=wrapped(project_name.upper(),23,content_width-10)[:2]
        base=height-78
        for row in title_rows:
            text_line(row,left,base,23,True,WHITE)
            base -= 26
        text_line(f'REUNIÃO · {date_text}',left,height-132,8.5,True,ICE)
        y=height-header_h-18

        # Identificação.
        meta_h=54
        rect(left,y-meta_h+5,content_width,meta_h,WHITE,LINE,0.6)
        labels=[
            ('RESPONSÁVEL DO PROJETO',owner_name or '—'),
            ('DURAÇÃO',duration_text or '—'),
            ('STATUS',meeting_status),
            ('DOCUMENTOS',str(len(attachments or []))),
        ]
        widths=[.38,.18,.27,.17]
        x=left
        for idx,(label,value) in enumerate(labels):
            w=content_width*widths[idx]
            text_line(label,x+10,y-11,6.2,True,MUTED)
            text_line(value,x+10,y-29,8.4,True,FUCHSIA if label=='STATUS' else BLACK)
            if idx:
                line(x,y-meta_h+10,x,y-4,LINE,.5)
            x += w
        y -= meta_h+14

        executive_card(document.get('executiveSummary') or '', document.get('executiveHighlights') or [])
        metrics_row()

        if document.get('evolution'):
            section_title('Evolução desde a última reunião')
            evolution_block(document.get('evolution') or [])

        section_title('Decisões e pontos estratégicos')
        numbered_points(document.get('keyPoints') or [])

        section_title('Ações sugeridas')
        action_list(document.get('suggestedActions') or [])

        if document.get('attentionPoints'):
            section_title('Pontos de atenção')
            attention_block(document.get('attentionPoints') or [])

        section_title('Impacto no Roadmap do Sucesso','Leitura executiva. Este bloco não altera automaticamente o Roadmap.')
        roadmap_block(document.get('roadmapImpact') or [])

        section_title('Sumário da reunião','Contexto consolidado para quem não participou.')
        paragraph_block(document.get('meetingSummary') or '',9.5)

        if commitment:
            commitment_card(commitment)

        if attachments:
            section_title('Documentos da reunião')
            attachments_block(attachments)

        total_pages=len(pages)
        for page_index,commands in enumerate(pages,1):
            line_color=rgb(LINE)
            commands.append(f'0.5 w {line_color[0]:.3f} {line_color[1]:.3f} {line_color[2]:.3f} RG {left:.2f} 34.00 m {width-right:.2f} 34.00 l S')
            muted=rgb(MUTED)
            footer_left=_pdf_escape('TRANSFORMAÇÃO KAZ · REGISTRO EXECUTIVO')
            footer_right=_pdf_escape(f'Página {page_index} de {total_pages}')
            commands.append(f'BT /F1 7.0 Tf {muted[0]:.3f} {muted[1]:.3f} {muted[2]:.3f} rg 1 0 0 1 {left:.2f} 21.00 Tm ({footer_left}) Tj ET')
            commands.append(f'BT /F1 7.0 Tf {muted[0]:.3f} {muted[1]:.3f} {muted[2]:.3f} rg 1 0 0 1 {width-right-58:.2f} 21.00 Tm ({footer_right}) Tj ET')

        objects=[None]
        objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
        page_ids=[5+index*2 for index in range(len(pages))]
        kids=' '.join(f'{obj_id} 0 R' for obj_id in page_ids)
        objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>'.encode('ascii'))
        objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
        objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')

        for page_index,commands in enumerate(pages):
            page_obj_id=5+page_index*2
            content_obj_id=page_obj_id+1
            page_obj=(
                f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] '
                f'/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_obj_id} 0 R >>'
            ).encode('ascii')
            stream=('\n'.join(commands)+'\n').encode('latin1',errors='replace')
            content_obj=f'<< /Length {len(stream)} >>\nstream\n'.encode('ascii')+stream+b'endstream'
            objects.append(page_obj)
            objects.append(content_obj)

        output=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets=[0]
        for obj_id in range(1,len(objects)):
            offsets.append(len(output))
            output.extend(f'{obj_id} 0 obj\n'.encode('ascii'))
            output.extend(objects[obj_id])
            output.extend(b'\nendobj\n')
        xref_offset=len(output)
        output.extend(f'xref\n0 {len(objects)}\n'.encode('ascii'))
        output.extend(b'0000000000 65535 f \n')
        for obj_id in range(1,len(objects)):
            output.extend(f'{offsets[obj_id]:010d} 00000 n \n'.encode('ascii'))
        output.extend(
            f'trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n'.encode('ascii')
        )
        return bytes(output)

    @app.route('/api/meeting/history/<session_id>/pdf')
    @app_module.login_required
    def meeting_summary_pdf(session_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        row = db.session.execute(text("""
            SELECT id, project_id, created_by, started_at, ended_at
              FROM kaz_meeting_audio_sessions
             WHERE id=:session_id
        """), {'session_id': session_id}).mappings().first()
        if not row:
            abort(404)
        if not _can_view_project(user, row['project_id'], payload):
            abort(403)

        saved = _saved_meeting(payload, session_id, row['project_id'])
        if not saved or not saved.get('aiProcessed'):
            return jsonify({'error': 'O registro executivo da reunião ainda não foi processado pela IA.'}), 409

        document = _normalize_ai_document(saved)
        project = app_module.find_project(payload, row['project_id']) or {}

        attachment_rows = db.session.execute(text("""
            SELECT name, size, uploaded_by, created_at
              FROM kaz_meeting_attachments
             WHERE session_id=:session_id
             ORDER BY created_at ASC, id ASC
        """), {'session_id': session_id}).mappings().all()
        attachments = [{
            'name': item['name'],
            'meta': ' · '.join(filter(None, [
                f"{round((item['size'] or 0)/1024)} KB" if item['size'] else '',
                item['uploaded_by'] or '',
                item['created_at'].strftime('%d/%m/%Y') if item['created_at'] else '',
            ])),
        } for item in attachment_rows]

        meeting_status = 'Reunião completa' if attachment_rows else 'Reunião finalizada'
        date_text = row['started_at'].strftime('%d/%m/%Y') if row['started_at'] else '-'
        duration_text = '—'
        if row['started_at']:
            seconds = max(0, int(((row['ended_at'] or row['started_at']) - row['started_at']).total_seconds()))
            hours, remainder = divmod(seconds, 3600)
            minutes = remainder // 60
            duration_text = f'{hours}h {minutes:02d}min' if hours else f'{minutes}min'

        commitment = (saved.get('nextWeek') or '').strip()
        pdf = _native_meeting_pdf(
            project.get('name') or row['project_id'],
            date_text,
            project.get('owner') or '—',
            duration_text,
            meeting_status,
            document,
            commitment,
            attachments,
        )
        filename = f"registro_executivo_{row['project_id']}_{(row['started_at'] or datetime.utcnow()).strftime('%Y-%m-%d')}.pdf"
        disposition = 'attachment' if request.args.get('download') == '1' else 'inline'
        return Response(pdf, mimetype='application/pdf', headers={
            'Content-Disposition': f'{disposition}; filename="{filename}"',
        })

    with app.app_context():
        db.create_all()
        _migrate_projects_once()

    if 'meeting_history_list' in app.view_functions:
        app.view_functions['meeting_history_list'] = meeting_history_list_v9
    if 'meeting_history_detail' in app.view_functions:
        app.view_functions['meeting_history_detail'] = meeting_history_detail_v9
    if 'update_meeting_commitment' in app.view_functions:
        app.view_functions['update_meeting_commitment'] = update_meeting_commitment_v9
    if 'summarize_meeting' in app.view_functions:
        app.view_functions['summarize_meeting'] = summarize_meeting_v9

    app.logger.info('Meeting/Documents V9 registered.')
