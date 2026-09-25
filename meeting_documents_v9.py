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

        next_steps = []
        for item in (doc.get('nextSteps') or []):
            if isinstance(item, dict):
                text_value = str(item.get('text') or '').strip()
                if text_value:
                    next_steps.append({
                        'text': text_value,
                        'responsible': str(item.get('responsible') or '').strip(),
                        'deadline': str(item.get('deadline') or '').strip(),
                    })

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

        if version >= 2 or any(key in doc for key in ('executiveSummary', 'keyPoints', 'nextSteps', 'attentionPoints')):
            return {
                'version': 3 if version >= 3 or evolution or roadmap_impact else 2,
                'executiveSummary': str(doc.get('executiveSummary') or '').strip(),
                'keyPoints': key_points,
                'nextSteps': next_steps,
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
            'keyPoints': [{'type': 'important', 'text': str(item).strip()} for item in legacy_points if str(item).strip()],
            'nextSteps': [],
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
                'isLegacyAiDocument': bool((saved or {}).get('aiProcessed') and (ai_document.get('version') or 1) < 2),
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
        roadmap_context = []
        for milestone in (project.get('milestones') or [])[:30]:
            roadmap_context.append(
                f"- {milestone.get('name') or 'Marco'} | status: {milestone.get('status') or '—'}"
            )
        project_context = f"""OBJETIVO DO PROJETO:
{(project.get('objective') or 'Não informado.').strip()}

ROADMAP DO SUCESSO — CONTEXTO, NÃO FONTE DE DECISÕES DA REUNIÃO:
{chr(10).join(roadmap_context) if roadmap_context else 'Não informado.'}"""

        prompt = f"""Você produz o REGISTRO EXECUTIVO das reuniões da Transformação KAZ.

Sua função NÃO é transcrever a conversa e NÃO é simplesmente encurtar a transcrição. Você deve interpretar a reunião como um profissional de gestão e registrar apenas o que tem valor para acompanhamento executivo do projeto.

PROJETO: {project.get('name') or project_id}

PRINCÍPIOS OBRIGATÓRIOS:
1. A TRANSCRIÇÃO é a principal fonte de verdade.
2. Arquivos anexados e contexto do projeto servem somente para compreensão. Não transforme conteúdo de apoio em decisão da reunião se ele não tiver sido efetivamente discutido.
3. Elimine vícios de fala, repetições, interrupções, exemplos laterais, brincadeiras e conversas sem relevância para o projeto.
4. Não siga obrigatoriamente a ordem cronológica da conversa. Organize por importância executiva.
5. Diferencie com rigor:
   - discussão: tema debatido, mas sem definição;
   - decisão: definição efetivamente tomada;
   - pendência/próximo passo: ação que precisa acontecer;
   - ponto de atenção: risco, bloqueio, divergência, dependência ou falta de definição.
6. Nunca transforme hipótese, sugestão, pergunta ou comentário em decisão.
7. Nunca invente responsável, prazo, número, decisão, risco ou conclusão.
8. Quando responsável ou prazo não estiverem claros, use string vazia.
9. Use linguagem executiva, direta, profissional e natural. Evite frases genéricas como "foi discutido que" quando for possível registrar o fato de forma objetiva.
10. O compromisso oficial da próxima reunião é um campo do sistema. NÃO crie, altere ou deduza esse compromisso.
11. Não mencione "transcrição", "áudio", "prompt", "IA" ou o processo de geração no conteúdo executivo.
12. Não use markdown. Responda SOMENTE um objeto JSON válido.

QUALIDADE ESPERADA POR BLOCO:

executiveSummary:
- um único texto executivo de aproximadamente 80 a 130 palavras;
- equivalente a 4–6 linhas em um documento;
- deve explicar foco da reunião, principais avanços/definições e situação do projeto ao final;
- não repetir todos os bullets abaixo.

keyPoints:
- somente decisões e informações estratégicas importantes;
- cada item deve ter type = "decision" ou "important";
- textos curtos, concretos e autossuficientes;
- em geral 3 a 8 itens, mas use menos se a reunião não justificar.

nextSteps:
- somente pendências e próximos passos reais;
- cada item contém text, responsible e deadline;
- responsible e deadline ficam vazios quando não houver certeza;
- não inclua o compromisso oficial da próxima reunião apenas porque ele aparece abaixo; só inclua uma ação se ela também estiver sustentada pela reunião.

attentionPoints:
- inclua somente riscos, dependências, bloqueios, divergências, atrasos ou pontos ainda sem definição que sejam relevantes;
- retorne [] quando não houver nada relevante.

meetingSummary:
- síntese mais completa, em 3 a 6 parágrafos curtos;
- deve permitir que alguém que não participou entenda contexto, raciocínio, assuntos centrais, decisões e encaminhamentos em 2–3 minutos;
- continua sendo síntese executiva, não ata e não transcrição.

FORMATO EXATO:
{{
  "executiveSummary": "texto",
  "keyPoints": [
    {{"type": "decision", "text": "texto"}},
    {{"type": "important", "text": "texto"}}
  ],
  "nextSteps": [
    {{"text": "texto", "responsible": "nome ou vazio", "deadline": "prazo ou vazio"}}
  ],
  "attentionPoints": ["texto"],
  "meetingSummary": "texto com parágrafos separados por duas quebras de linha"
}}

{project_context}

COMPROMISSO OFICIAL DA PRÓXIMA REUNIÃO — NÃO ALTERAR NEM DEDUZIR:
{commitment or 'Não informado.'}

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

ARQUIVOS ANEXADOS — APENAS CONTEXTO COMPLEMENTAR:
{'\n\n'.join(docs) if docs else 'Nenhum arquivo com conteúdo textual extraível.'}
"""
        try:
            response = requests.post(
                'https://api.openai.com/v1/responses',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': os.environ.get('MEETING_SUMMARY_MODEL', 'gpt-5.6-luna'), 'input': prompt},
                timeout=240,
            )
            if response.status_code >= 400:
                app.logger.error('Falha no resumo IA executivo V2: %s', response.text[:1000])
                return jsonify({'error': 'A gravação foi preservada, mas a IA não conseguiu processar o registro executivo.'}), 502

            raw_text = _clean_json_text(_response_text(response.json()))
            try:
                structured = json.loads(raw_text)
            except Exception:
                app.logger.error('Resposta IA V2 não era JSON: %s', raw_text[:1000])
                return jsonify({'error': 'A IA respondeu, mas o registro executivo não veio no formato esperado. Tente reprocessar.'}), 502

            executive_summary = str(structured.get('executiveSummary') or '').strip()
            meeting_summary = str(structured.get('meetingSummary') or '').strip()

            key_points = []
            for item in (structured.get('keyPoints') or []):
                if isinstance(item, dict):
                    text_value = str(item.get('text') or '').strip()
                    if text_value:
                        key_points.append({
                            'type': item.get('type') if item.get('type') in ('decision', 'important') else 'important',
                            'text': text_value,
                        })
                elif str(item).strip():
                    key_points.append({'type': 'important', 'text': str(item).strip()})

            next_steps = []
            for item in (structured.get('nextSteps') or []):
                if isinstance(item, dict):
                    text_value = str(item.get('text') or '').strip()
                    if text_value:
                        next_steps.append({
                            'text': text_value,
                            'responsible': str(item.get('responsible') or '').strip(),
                            'deadline': str(item.get('deadline') or '').strip(),
                        })

            attention = structured.get('attentionPoints') or []
            if isinstance(attention, str):
                attention = [line.strip(' -•\t') for line in attention.splitlines() if line.strip()]
            attention = [str(item).strip() for item in attention if str(item).strip()]

            if not executive_summary or not meeting_summary:
                return jsonify({'error': 'A IA não retornou conteúdo suficiente para o registro executivo.'}), 502

            document = {
                'version': 2,
                'executiveSummary': executive_summary,
                'keyPoints': key_points,
                'nextSteps': next_steps,
                'attentionPoints': attention,
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
            saved['aiDocumentVersion'] = 2
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
                'aiDocumentVersion': 2,
                'document': document,
                'summary': executive_summary,
                'revision': state.revision,
            })
        except requests.RequestException:
            app.logger.exception('Falha de comunicação com IA da reunião V2')
            return jsonify({'error': 'Falha de comunicação com a IA da reunião.'}), 502

    def _pdf_escape(value):
        raw = str(value or '').replace('\r', ' ').replace('\t', ' ')
        encoded = raw.encode('cp1252', errors='replace').decode('latin1')
        return encoded.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    def _native_meeting_pdf(project_name, date_text, created_by, duration_text, meeting_status, document, commitment, attachments):
        width, height = 595.28, 841.89
        left, right, top, bottom = 46.0, 46.0, 46.0, 50.0
        content_width = width - left - right
        y = height - top
        pages = [[]]

        NAVY = '#10213B'
        BLUE = '#285BC7'
        BLUE_SOFT = '#EEF4FF'
        BLUE_BORDER = '#CEDBFA'
        TEXT = '#26374A'
        MUTED = '#6A788A'
        LINE = '#E3E9F0'
        GREEN = '#16805A'
        GREEN_SOFT = '#EAF8F2'
        AMBER = '#9A6413'
        AMBER_SOFT = '#FFF7E7'
        PANEL = '#F7F9FC'
        WHITE = '#FFFFFF'

        def rgb(hex_value):
            value = hex_value.lstrip('#')
            return tuple(int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4))

        def new_page():
            nonlocal y
            pages.append([])
            y = height - top

        def ensure_space(required):
            nonlocal y
            if y - required < bottom + 22:
                new_page()
                return True
            return False

        def rect(x, y0, w, h, fill=None, stroke=None, line_width=0.8):
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

        def line(x1, y1, x2, y2, color=LINE, line_width=0.7):
            r, g, b = rgb(color)
            pages[-1].append(f'{line_width:.2f} w {r:.3f} {g:.3f} {b:.3f} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S')

        def text_line(value, x, baseline, size=10, bold=False, color=TEXT):
            r, g, b = rgb(color)
            font = 'F2' if bold else 'F1'
            safe = _pdf_escape(value)
            pages[-1].append(
                f'BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {x:.2f} {baseline:.2f} Tm ({safe}) Tj ET'
            )

        def wrapped(value, size=10, max_width=None):
            value = str(value or '').strip()
            if not value:
                return []
            max_width = max_width or content_width
            avg = max(size * 0.49, 4.3)
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

        def section_label(title, subtitle=''):
            nonlocal y
            ensure_space(42)
            text_line(title.upper(), left, y, 9.2, True, BLUE)
            y -= 14
            if subtitle:
                for row in wrapped(subtitle, 8.2, content_width):
                    text_line(row, left, y, 8.2, False, MUTED)
                    y -= 11
            y -= 4

        def executive_card(body):
            nonlocal y
            rows = wrapped(body, 10.5, content_width - 40)
            card_h = 34 + max(1, len(rows)) * 15
            ensure_space(card_h + 16)
            rect(left, y-card_h+8, content_width, card_h, BLUE_SOFT, BLUE_BORDER, 0.8)
            rect(left, y-card_h+8, 5, card_h, BLUE, None)
            text_line('RESUMO EXECUTIVO', left+20, y-13, 8.8, True, BLUE)
            baseline = y-35
            for row in rows:
                if row:
                    text_line(row, left+20, baseline, 10.5, False, TEXT)
                baseline -= 15
            y -= card_h + 10

        def numbered_point(number, point_type, body):
            nonlocal y
            rows = wrapped(body, 9.7, content_width - 82)
            card_h = 26 + max(1, len(rows))*13
            ensure_space(card_h + 8)
            rect(left, y-card_h+6, content_width, card_h, WHITE, LINE, 0.8)
            rect(left+12, y-24, 26, 22, BLUE, None)
            text_line(str(number).zfill(2), left+18, y-18, 8.5, True, WHITE)
            label = 'DECISÃO' if point_type == 'decision' else 'IMPORTANTE'
            label_color = GREEN if point_type == 'decision' else BLUE
            text_line(label, left+52, y-12, 7.8, True, label_color)
            baseline=y-30
            for row in rows:
                text_line(row, left+52, baseline, 9.7, False, TEXT)
                baseline -= 13
            y -= card_h + 6

        def next_steps_table(items):
            nonlocal y
            if not items:
                ensure_space(34)
                rect(left, y-26, content_width, 30, PANEL, LINE, 0.7)
                text_line('Nenhuma pendência ou próximo passo foi identificado com segurança.', left+12, y-14, 9, False, MUTED)
                y -= 38
                return
            col1 = content_width * 0.57
            col2 = content_width * 0.23
            col3 = content_width - col1 - col2
            ensure_space(38)
            rect(left, y-26, content_width, 30, NAVY, None)
            text_line('PRÓXIMO PASSO', left+10, y-15, 7.8, True, WHITE)
            text_line('RESPONSÁVEL', left+col1+10, y-15, 7.8, True, WHITE)
            text_line('PRAZO', left+col1+col2+10, y-15, 7.8, True, WHITE)
            y -= 32
            for item in items:
                step_lines=wrapped(item.get('text') or '', 8.8, col1-20)
                resp_lines=wrapped(item.get('responsible') or '—', 8.5, col2-20)
                deadline_lines=wrapped(item.get('deadline') or '—', 8.5, col3-20)
                count=max(len(step_lines),len(resp_lines),len(deadline_lines),1)
                row_h=16+count*12
                ensure_space(row_h+4)
                rect(left, y-row_h+5, content_width, row_h, WHITE, LINE, 0.6)
                baseline=y-12
                for idx,row in enumerate(step_lines or ['—']):
                    text_line(row, left+10, baseline-idx*12, 8.8, False, TEXT)
                for idx,row in enumerate(resp_lines or ['—']):
                    text_line(row, left+col1+10, baseline-idx*12, 8.5, False, TEXT)
                for idx,row in enumerate(deadline_lines or ['—']):
                    text_line(row, left+col1+col2+10, baseline-idx*12, 8.5, False, TEXT)
                y -= row_h + 3

        def attention_card(items):
            nonlocal y
            if not items:
                return
            blocks=[]
            total_lines=0
            for item in items:
                lines=wrapped(item,9.2,content_width-44)
                blocks.append(lines)
                total_lines += max(1,len(lines))
            card_h=30+total_lines*13+len(items)*5
            ensure_space(card_h+12)
            rect(left,y-card_h+6,content_width,card_h,AMBER_SOFT,'#F0D7A8',0.8)
            text_line('PONTOS DE ATENÇÃO',left+16,y-13,8.7,True,AMBER)
            baseline=y-34
            for lines in blocks:
                text_line('•',left+17,baseline,9.5,True,AMBER)
                for idx,row in enumerate(lines):
                    text_line(row,left+31,baseline-idx*13,9.2,False,TEXT)
                baseline -= max(1,len(lines))*13+5
            y -= card_h+9

        def body_paragraphs(value):
            nonlocal y
            paragraphs=[p.strip() for p in re.split(r'\n\s*\n',str(value or '')) if p.strip()]
            for paragraph in paragraphs:
                rows=wrapped(paragraph,9.6,content_width)
                ensure_space(max(32,len(rows)*14+12))
                for row in rows:
                    text_line(row,left,y,9.6,False,TEXT)
                    y-=14
                y-=8

        def commitment_card(value):
            nonlocal y
            if not value:
                return
            rows=wrapped(value,10,content_width-40)
            card_h=34+len(rows)*14
            ensure_space(card_h+12)
            rect(left,y-card_h+6,content_width,card_h,NAVY,None)
            text_line('PRÓXIMA REUNIÃO · COMPROMISSO',left+18,y-13,8.3,True,'#9EC1FF')
            baseline=y-35
            for row in rows:
                text_line(row,left+18,baseline,10,True,WHITE)
                baseline-=14
            y-=card_h+10

        def attachments_block(items):
            nonlocal y
            if not items:
                return
            section_label('Documentos da reunião')
            for item in items:
                rows=wrapped(item.get('name') or 'Arquivo',8.8,content_width-95)
                row_h=max(30,14+len(rows)*11)
                ensure_space(row_h+3)
                rect(left,y-row_h+5,content_width,row_h,PANEL,LINE,0.6)
                text_line('DOC',left+12,y-14,7.2,True,BLUE)
                for idx,row in enumerate(rows):
                    text_line(row,left+48,y-12-idx*11,8.8,True,TEXT)
                meta=item.get('meta') or ''
                if meta:
                    text_line(meta,left+48,y-row_h+13,7.5,False,MUTED)
                y-=row_h+4

        # Cabeçalho editorial
        header_h=124
        rect(0,height-header_h,width,header_h,NAVY,None)
        text_line('TRANSFORMAÇÃO KAZ',left,height-34,8.5,True,'#9EC1FF')
        title_rows=wrapped(project_name,20,content_width-10)[:2]
        baseline=height-62
        for row in title_rows:
            text_line(row,left,baseline,20,True,WHITE)
            baseline-=24
        text_line(f'Reunião de {date_text}',left,height-112,8.6,False,'#D8E4F6')
        y=height-header_h-22

        # Metadados
        meta_h=52
        rect(left,y-meta_h+6,content_width,meta_h,WHITE,LINE,0.8)
        labels=[
            ('RESPONSÁVEL',created_by or '—'),
            ('DURAÇÃO',duration_text or '—'),
            ('STATUS',meeting_status),
            ('IA','Processado com sucesso'),
        ]
        col=content_width/4
        for idx,(label,value) in enumerate(labels):
            x=left+idx*col+10
            text_line(label,x,y-10,6.8,True,MUTED)
            value_color=GREEN if label in ('STATUS','IA') else TEXT
            text_line(value,x,y-27,8.3,True,value_color)
            if idx:
                line(left+idx*col,y-meta_h+12,left+idx*col,y-4,LINE,0.6)
        y-=meta_h+18

        executive_card(document.get('executiveSummary') or '')

        section_label('Decisões e pontos importantes')
        points=document.get('keyPoints') or []
        if points:
            for idx,item in enumerate(points,1):
                numbered_point(idx,item.get('type') or 'important',item.get('text') or '')
        else:
            rect(left,y-26,content_width,30,PANEL,LINE,0.7)
            text_line('Nenhuma decisão ou ponto estratégico adicional foi identificado.',left+12,y-14,9,False,MUTED)
            y-=38

        section_label('Pendências e próximos passos')
        next_steps_table(document.get('nextSteps') or [])

        if document.get('attentionPoints'):
            section_label('Pontos de atenção')
            attention_card(document.get('attentionPoints') or [])

        section_label('Sumário da reunião','Contexto consolidado para quem não participou da reunião.')
        body_paragraphs(document.get('meetingSummary') or '')

        commitment_card(commitment)
        attachments_block(attachments)

        # Rodapé com paginação.
        total_pages=len(pages)
        for page_index,commands in enumerate(pages,1):
            line_color=rgb(LINE)
            commands.append(f'0.6 w {line_color[0]:.3f} {line_color[1]:.3f} {line_color[2]:.3f} RG {left:.2f} 36.00 m {width-right:.2f} 36.00 l S')
            muted=rgb('#8C99A8')
            footer_left=_pdf_escape('Transformação KAZ · Registro Executivo da Reunião')
            footer_right=_pdf_escape(f'Página {page_index} de {total_pages}')
            commands.append(f'BT /F1 7.2 Tf {muted[0]:.3f} {muted[1]:.3f} {muted[2]:.3f} rg 1 0 0 1 {left:.2f} 22.00 Tm ({footer_left}) Tj ET')
            commands.append(f'BT /F1 7.2 Tf {muted[0]:.3f} {muted[1]:.3f} {muted[2]:.3f} rg 1 0 0 1 {width-right-58:.2f} 22.00 Tm ({footer_right}) Tj ET')

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
            row['created_by'] or '',
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
