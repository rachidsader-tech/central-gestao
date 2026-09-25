import html
import io
import json
import os
import re
import zipfile
from datetime import datetime

import requests
from flask import request, jsonify, Response, abort
from sqlalchemy import text
from werkzeug.utils import secure_filename

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


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
                'status': milestone.status if milestone.status in app_module.PROJECT_STATUSES else 'Não iniciado',
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
            'status': source.status if source.status in app_module.PROJECT_STATUSES else 'Não iniciado',
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

        ai_document = (saved or {}).get('aiDocument')
        if not isinstance(ai_document, dict):
            legacy_summary = ((saved or {}).get('summary') or '').strip()
            ai_document = {
                'summary': legacy_summary,
                'importantPoints': [],
                'meetingSummary': legacy_summary,
            }

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
            'canGenerateAi': bool(app_module.can_edit_project(user, row['project_id'])),
            'transcript': transcript,
            'review': {
                'commitment': (saved or {}).get('nextWeek') or '',
                'aiProcessed': bool((saved or {}).get('aiProcessed')),
                'aiProcessedAt': (saved or {}).get('aiProcessedAt') or '',
                'aiSummaryStatus': (saved or {}).get('aiSummaryStatus') or ('success' if (saved or {}).get('aiProcessed') else ''),
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
        if not project_id or not app_module.can_edit_project(user, project_id):
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
        prompt = f"""Você é o secretário executivo da Transformação KAZ.
Analise a reunião do projeto {project.get('name') or project_id} e produza um documento executivo fiel ao que ocorreu.

Regras:
- Não invente fatos, decisões, responsáveis, prazos ou pendências.
- Use a transcrição como fonte principal. Use os arquivos anexados apenas como contexto complementar.
- O compromisso da próxima reunião foi informado manualmente e não deve ser criado pela IA.
- Responda SOMENTE JSON válido, sem markdown.

Estrutura obrigatória:
summary: string com 5 a 6 linhas curtas, resumindo a reunião de forma executiva;
importantPoints: array de strings com os pontos importantes da reunião. Inclua somente decisões, pendências, encaminhamentos e itens estratégicos efetivamente discutidos;
meetingSummary: string com um sumário mais completo e organizado da reunião, em texto corrido com parágrafos.

COMPROMISSO OFICIAL DA PRÓXIMA REUNIÃO:
{commitment or 'Não informado.'}

TRANSCRIÇÃO:
{transcript}

ARQUIVOS ANEXADOS:
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
                app.logger.error('Falha no resumo IA v9: %s', response.text[:1000])
                return jsonify({'error': 'A gravação foi preservada, mas a IA não conseguiu processar o resumo.'}), 502
            raw_text = _clean_json_text(_response_text(response.json()))
            try:
                structured = json.loads(raw_text)
            except Exception:
                app.logger.error('Resposta IA não era JSON: %s', raw_text[:1000])
                return jsonify({'error': 'A IA respondeu, mas o resumo não veio no formato esperado. Tente reprocessar.'}), 502

            summary = (structured.get('summary') or '').strip()
            points = structured.get('importantPoints') or []
            if isinstance(points, str):
                points = [line.strip(' -•\t') for line in points.splitlines() if line.strip()]
            points = [str(item).strip() for item in points if str(item).strip()]
            meeting_summary = (structured.get('meetingSummary') or '').strip()
            if not summary or not meeting_summary:
                return jsonify({'error': 'A IA não retornou conteúdo suficiente para o documento da reunião.'}), 502

            state = _state_locked()
            payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
            saved = _saved_meeting(payload, session_id, project_id)
            if not saved:
                return jsonify({'error': 'Reunião salva não encontrada.'}), 404
            document = {
                'summary': summary,
                'importantPoints': points,
                'meetingSummary': meeting_summary,
            }
            saved['summary'] = summary
            saved['aiDocument'] = document
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
                'document': document,
                'summary': summary,
                'revision': state.revision,
            })
        except requests.RequestException:
            app.logger.exception('Falha de comunicação com IA da reunião v9')
            return jsonify({'error': 'Falha de comunicação com a IA da reunião.'}), 502

    def _pdf_paragraph(value, style):
        safe = html.escape(str(value or '')).replace('\n', '<br/>')
        return Paragraph(safe, style)

    @app.route('/api/meeting/history/<session_id>/pdf')
    @app_module.login_required
    def meeting_summary_pdf(session_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        row = db.session.execute(text("""
            SELECT id, project_id, created_by, started_at
              FROM kaz_meeting_audio_sessions
             WHERE id=:session_id
        """), {'session_id': session_id}).mappings().first()
        if not row:
            abort(404)
        if not _can_view_project(user, row['project_id'], payload):
            abort(403)
        saved = _saved_meeting(payload, session_id, row['project_id'])
        if not saved or not saved.get('aiProcessed'):
            return jsonify({'error': 'O resumo da reunião ainda não foi processado pela IA.'}), 409
        document = saved.get('aiDocument') or {}
        if not isinstance(document, dict):
            document = {}
        summary = (document.get('summary') or saved.get('summary') or '').strip()
        points = document.get('importantPoints') or []
        meeting_summary = (document.get('meetingSummary') or saved.get('summary') or '').strip()
        if isinstance(points, str):
            points = [x.strip() for x in points.splitlines() if x.strip()]
        project = app_module.find_project(payload, row['project_id']) or {}
        attachment_count = db.session.execute(text("""
            SELECT COUNT(*) FROM kaz_meeting_attachments WHERE session_id=:session_id
        """), {'session_id': session_id}).scalar() or 0
        meeting_status = 'Reunião completa' if attachment_count else 'Reunião finalizada'

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
            title=f"Resumo da reunião - {project.get('name') or row['project_id']}",
            author='Transformação KAZ',
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'KazTitle', parent=styles['Title'], fontName='Helvetica-Bold',
            fontSize=19, leading=23, textColor=colors.HexColor('#12233F'), spaceAfter=7,
        )
        meta_style = ParagraphStyle(
            'KazMeta', parent=styles['Normal'], fontSize=8.5, leading=12,
            textColor=colors.HexColor('#64748B'), spaceAfter=14,
        )
        section_style = ParagraphStyle(
            'KazSection', parent=styles['Heading2'], fontName='Helvetica-Bold',
            fontSize=12, leading=15, textColor=colors.HexColor('#163E72'),
            spaceBefore=8, spaceAfter=7,
        )
        body_style = ParagraphStyle(
            'KazBody', parent=styles['BodyText'], fontSize=10, leading=15,
            textColor=colors.HexColor('#24364B'), spaceAfter=8,
        )
        small_style = ParagraphStyle(
            'KazSmall', parent=styles['BodyText'], fontSize=8.5, leading=12,
            textColor=colors.HexColor('#53657A'),
        )
        badge_style = ParagraphStyle(
            'KazBadge', parent=small_style, alignment=TA_CENTER, fontName='Helvetica-Bold',
            textColor=colors.HexColor('#166534'),
        )
        story = []
        story.append(_pdf_paragraph('Resumo da reunião', title_style))
        date_text = row['started_at'].strftime('%d/%m/%Y %H:%M') if row['started_at'] else '-'
        story.append(_pdf_paragraph(
            f"{project.get('name') or row['project_id']} | {date_text} | {row['created_by'] or ''}",
            meta_style,
        ))
        status_table = Table(
            [[Paragraph(html.escape(meeting_status), badge_style),
              Paragraph('Resumo IA processado com sucesso', badge_style)]],
            colWidths=[55*mm, 75*mm],
        )
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ECFDF3')),
            ('BOX', (0,0), (-1,-1), 0.6, colors.HexColor('#B7E4C7')),
            ('INNERGRID', (0,0), (-1,-1), 0.4, colors.HexColor('#D4ECDD')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.extend([status_table, Spacer(1, 7*mm)])

        story.append(_pdf_paragraph('Resumo da reunião', section_style))
        story.append(_pdf_paragraph(summary, body_style))

        story.append(_pdf_paragraph('Pontos importantes', section_style))
        if points:
            for item in points:
                block = Table(
                    [[Paragraph('-', body_style), _pdf_paragraph(item, body_style)]],
                    colWidths=[5*mm, 160*mm],
                )
                block.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
                story.append(KeepTogether(block))
        else:
            story.append(_pdf_paragraph('Nenhum ponto adicional foi identificado com segurança.', body_style))

        story.append(_pdf_paragraph('Sumário da reunião', section_style))
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', meeting_summary) if p.strip()]
        if not paragraphs:
            paragraphs = [meeting_summary]
        for paragraph in paragraphs:
            story.append(_pdf_paragraph(paragraph, body_style))

        commitment = (saved.get('nextWeek') or '').strip()
        if commitment:
            story.append(Spacer(1, 3*mm))
            story.append(_pdf_paragraph('Compromisso da próxima reunião', section_style))
            story.append(_pdf_paragraph(commitment, body_style))

        def footer(canvas, doc_obj):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor('#E2E8F0'))
            canvas.line(18*mm, 13*mm, A4[0]-18*mm, 13*mm)
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(colors.HexColor('#94A3B8'))
            canvas.drawString(18*mm, 8*mm, 'Transformação KAZ')
            canvas.drawRightString(A4[0]-18*mm, 8*mm, f'Página {doc_obj.page}')
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        pdf = buffer.getvalue()
        filename = f"resumo_reuniao_{row['project_id']}_{(row['started_at'] or datetime.utcnow()).strftime('%Y-%m-%d')}.pdf"
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
