import os
import json
import secrets
import hashlib
import io
import re
import zipfile
from datetime import datetime

import requests
from flask import request, jsonify, Response, abort
from sqlalchemy import UniqueConstraint
from werkzeug.utils import secure_filename


def register(app_module):
    app = app_module.app
    db = app_module.db

    class MeetingAudioSession(db.Model):
        __tablename__ = 'kaz_meeting_audio_sessions'
        id = db.Column(db.String(64), primary_key=True)
        project_id = db.Column(db.String(100), nullable=False, index=True)
        created_by = db.Column(db.String(160), nullable=False)
        status = db.Column(db.String(40), nullable=False, default='recording')
        started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        ended_at = db.Column(db.DateTime, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class MeetingAudioSegment(db.Model):
        __tablename__ = 'kaz_meeting_audio_segments'
        id = db.Column(db.Integer, primary_key=True)
        session_id = db.Column(db.String(64), db.ForeignKey('kaz_meeting_audio_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
        position = db.Column(db.Integer, nullable=False)
        mime_type = db.Column(db.String(120), nullable=False, default='audio/webm')
        size = db.Column(db.Integer, nullable=False, default=0)
        file_data = db.Column(db.LargeBinary, nullable=False)
        transcript = db.Column(db.Text, nullable=False, default='')
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (UniqueConstraint('session_id', 'position', name='uq_kaz_meeting_segment_position'),)

    class MeetingAttachment(db.Model):
        __tablename__ = 'kaz_meeting_attachments'
        id = db.Column(db.Integer, primary_key=True)
        session_id = db.Column(db.String(64), db.ForeignKey('kaz_meeting_audio_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
        project_id = db.Column(db.String(100), nullable=False, index=True)
        name = db.Column(db.String(255), nullable=False)
        mime_type = db.Column(db.String(160), nullable=False, default='application/octet-stream')
        size = db.Column(db.Integer, nullable=False, default=0)
        file_data = db.Column(db.LargeBinary, nullable=False)
        uploaded_by = db.Column(db.String(160), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def _load_state_locked():
        return db.session.execute(
            app_module.select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
        ).scalar_one()

    def _project_or_404(state, project_id):
        p = app_module.find_project(state.payload, project_id)
        if not p:
            abort(404)
        return p

    def _can_manage_project(user, project_id):
        return bool(user and (user.username == 'rachid' or user.project_id == project_id))

    def _can_view_project(user, project_id):
        if not user:
            return False
        return True

    def _touch(state, user, payload):
        state.payload = json.loads(json.dumps(payload, ensure_ascii=False))
        state.revision = int(state.revision or 0) + 1
        state.updated_by = user.display_name
        state.updated_at = datetime.utcnow()
        db.session.commit()

    def _history(project, user, text):
        project.setdefault('history', []).append({
            'at': app_module.now_iso(),
            'author': user.display_name,
            'text': text,
        })
        project['lastUpdate'] = app_module.now_iso()

    def _reset_scope_open_once():
        marker = 'roadmap-sucesso-scope-open-v1'
        if app_module.MigrationBackup.query.filter_by(backup_key=marker).first():
            return
        state = db.session.get(app_module.AppState, 1)
        if not state:
            return
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        snapshot = []
        for p in payload.get('projects', []):
            snapshot.append({
                'id': p.get('id'),
                'milestonesLocked': bool(p.get('milestonesLocked')),
                'scopeDefined': bool(p.get('scopeDefined', p.get('milestonesLocked'))),
            })
            p['milestonesLocked'] = False
            p['scopeDefined'] = False
            p['milestonesLockedAt'] = ''
            p['milestonesLockedBy'] = ''
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        db.session.add(app_module.MigrationBackup(
            backup_key=marker,
            payload={'before': snapshot, 'action': 'all_project_scopes_opened_for_final_review'},
            checksum=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        ))
        state.payload = payload
        state.revision = int(state.revision or 0) + 1
        state.updated_by = 'Sistema · Roadmap do Sucesso'
        state.updated_at = datetime.utcnow()
        db.session.commit()

    with app.app_context():
        db.create_all()
        _reset_scope_open_once()
        app.logger.info('Roadmap do Sucesso ativo. Meeting AI configured=%s', bool(os.environ.get('OPENAI_API_KEY')))

    base_project_action = app.view_functions.get('project_action')

    @app_module.login_required
    def roadmap_project_action(project_id):
        app_module.require_csrf()
        body = request.get_json(force=True) or {}
        action = body.get('action')
        user = app_module.current_user()

        if action not in {
            'scope_define', 'scope_reopen', 'milestones_finalize', 'unlock_milestones',
            'milestone', 'milestone_add'
        }:
            return base_project_action(project_id)

        state = _load_state_locked()
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        project = app_module.find_project(payload, project_id)
        if not project:
            abort(404)

        if action in ('scope_define', 'milestones_finalize'):
            if not _can_manage_project(user, project_id):
                abort(403)
            if project.get('milestonesLocked'):
                return jsonify({'error': 'O escopo deste projeto já está definido.'}), 400
            project['milestonesLocked'] = True
            project['scopeDefined'] = True
            project['milestonesLockedAt'] = app_module.now_iso()
            project['milestonesLockedBy'] = user.display_name
            _history(project, user, 'Escopo do projeto definido. A estrutura existente do Roadmap do Sucesso foi congelada.')
            _touch(state, user, payload)
            return jsonify({'ok': True, 'revision': state.revision, 'scopeDefined': True})

        if action in ('scope_reopen', 'unlock_milestones'):
            if user.username != 'rachid':
                return jsonify({'error': 'Somente Rachid pode reabrir o escopo de um projeto definido.'}), 403
            project['milestonesLocked'] = False
            project['scopeDefined'] = False
            project['milestonesLockedAt'] = ''
            project['milestonesLockedBy'] = ''
            _history(project, user, 'Escopo do projeto reaberto por Rachid para revisão estrutural do Roadmap do Sucesso.')
            _touch(state, user, payload)
            return jsonify({'ok': True, 'revision': state.revision, 'scopeDefined': False})

        if action == 'milestone_add':
            if not _can_manage_project(user, project_id):
                return jsonify({'error': 'Somente o usuário alocado no projeto ou Rachid pode inserir novos itens no Roadmap do Sucesso.'}), 403
            name = (body.get('name') or '').strip()
            if not name:
                return jsonify({'error': 'Informe o nome do novo item do Roadmap do Sucesso.'}), 400
            status = (body.get('status') or 'Não iniciado').strip()
            if status not in app_module.PROJECT_STATUSES:
                status = 'Não iniciado'
            milestone = {
                'id': secrets.token_hex(6),
                'name': name,
                'status': status,
                'deadline': (body.get('deadline') or '').strip(),
                'conclusion': '',
                'memos': [],
                'createdAt': app_module.now_iso(),
                'createdBy': user.display_name,
                'addedAfterScopeDefined': bool(project.get('milestonesLocked')),
            }
            project.setdefault('milestones', []).append(milestone)
            when = ' após a definição do escopo' if project.get('milestonesLocked') else ''
            _history(project, user, f'Novo item incluído no Roadmap do Sucesso{when}: {name}.')
            _touch(state, user, payload)
            return jsonify({'ok': True, 'milestone': milestone, 'revision': state.revision})

        if action == 'milestone':
            if not app_module.can_edit_project(user, project_id):
                abort(403)
            milestone_id = str(body.get('milestoneId') or '')
            milestone = next((m for m in project.get('milestones', []) if str(m.get('id')) == milestone_id), None)
            if not milestone:
                abort(404)

            structure_open = not bool(project.get('milestonesLocked'))
            if structure_open:
                if 'name' in body:
                    name = (body.get('name') or '').strip()
                    if name:
                        milestone['name'] = name
                if 'deadline' in body and body.get('deadline') is not None:
                    milestone['deadline'] = (body.get('deadline') or '').strip()

            status = body.get('status')
            if status in app_module.PROJECT_STATUSES:
                milestone['status'] = status
            if 'conclusion' in body:
                milestone['conclusion'] = body.get('conclusion', '') or ''
            memo = (body.get('memo') or '').strip()
            if memo:
                milestone.setdefault('memos', []).append({
                    'at': app_module.now_iso(),
                    'author': user.display_name,
                    'text': memo,
                })

            if milestone.get('status') == 'Concluído' and not milestone.get('concludedAt'):
                milestone['concludedAt'] = app_module.now_iso()
            elif milestone.get('status') != 'Concluído':
                milestone['concludedAt'] = ''
            project['lastUpdate'] = app_module.now_iso()
            _touch(state, user, payload)
            return jsonify({'ok': True, 'revision': state.revision})

        return jsonify({'error': 'Ação inválida.'}), 400

    app.view_functions['project_action'] = roadmap_project_action

    @app.route('/api/projects/<project_id>/milestones/<milestone_id>/attachments', methods=['GET', 'POST'])
    @app_module.login_required
    def milestone_attachments(project_id, milestone_id):
        user = app_module.current_user()
        state = db.session.get(app_module.AppState, 1)
        project = _project_or_404(state, project_id)
        milestone = next((m for m in project.get('milestones', []) if str(m.get('id')) == str(milestone_id)), None)
        if not milestone:
            abort(404)
        if not _can_view_project(user, project_id):
            abort(403)

        if request.method == 'POST':
            app_module.require_csrf()
            if not app_module.can_edit_project(user, project_id):
                abort(403)
            f = request.files.get('file')
            if not f or not f.filename:
                return jsonify({'error': 'Selecione um arquivo.'}), 400
            raw = f.read()
            if not raw:
                return jsonify({'error': 'Arquivo vazio.'}), 400
            if len(raw) > 20 * 1024 * 1024:
                return jsonify({'error': 'O arquivo excede 20 MB.'}), 413
            name = secure_filename(f.filename) or 'arquivo'
            try:
                # O modelo ORM legado de Attachment ainda não declara dependency_id,
                # embora a coluna já exista no PostgreSQL. Não passamos esse campo
                # pelo construtor para manter compatibilidade com o modelo carregado.
                item = app_module.Attachment(
                    project_id=project_id,
                    milestone_id=str(milestone_id),
                    name=name,
                    note=(request.form.get('note') or '').strip(),
                    mime_type=f.mimetype or 'application/octet-stream',
                    size=len(raw),
                    file_data=raw,
                    uploaded_by=user.display_name,
                )
                db.session.add(item)
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception(
                    'Falha ao anexar arquivo no Roadmap: project=%s milestone=%s user=%s',
                    project_id, milestone_id, user.username,
                )
                return jsonify({'error': 'Não foi possível salvar o arquivo. Tente novamente.'}), 500

        rows = app_module.Attachment.query.filter_by(
            project_id=project_id, milestone_id=str(milestone_id)
        ).order_by(app_module.Attachment.created_at.desc(), app_module.Attachment.id.desc()).all()
        return jsonify({'attachments': [{
            'id': a.id,
            'name': a.name,
            'note': a.note or '',
            'mimeType': a.mime_type,
            'size': a.size,
            'uploadedBy': a.uploaded_by,
            'createdAt': a.created_at.isoformat() if a.created_at else '',
            'url': f'/api/milestone-attachments/{a.id}/download',
        } for a in rows]})

    @app.route('/api/milestone-attachments/<int:attachment_id>/download')
    @app_module.login_required
    def download_milestone_attachment(attachment_id):
        a = db.session.get(app_module.Attachment, attachment_id)
        if not a or not a.milestone_id:
            abort(404)
        if not _can_view_project(app_module.current_user(), a.project_id):
            abort(403)
        return Response(
            a.file_data,
            mimetype=a.mime_type or 'application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{a.name}"'},
        )

    def _saved_meeting(payload, session_id, project_id=None):
        return next((
            m for m in (payload.get('meetings') or [])
            if (m.get('audioSessionId') or '') == session_id
            and (not project_id or m.get('projectId') == project_id)
        ), None)

    def _sync_meeting_commitment(project, meeting, commitment, user):
        commitment = (commitment or '').strip()
        rows = project.setdefault('weeklyCommitments', [])
        source_id = meeting.get('id') or ''
        source_session = meeting.get('audioSessionId') or ''
        linked = next((
            c for c in rows
            if (source_id and c.get('sourceMeetingId') == source_id)
            or (source_session and c.get('sourceAudioSessionId') == source_session)
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
            'id': secrets.token_hex(6),
            'text': commitment,
            'status': 'Aberto',
            'author': user.display_name,
            'createdAt': app_module.now_iso(),
            'source': 'meeting',
            'sourceMeetingId': source_id,
            'sourceAudioSessionId': source_session,
        })

    def _meeting_attachment_payload(item):
        return {
            'id': item.id,
            'name': item.name,
            'mimeType': item.mime_type,
            'size': item.size,
            'uploadedBy': item.uploaded_by,
            'createdAt': item.created_at.isoformat() if item.created_at else '',
            'url': f'/api/meeting/attachments/{item.id}/download',
        }

    def _extract_meeting_attachment_text(item):
        raw = item.file_data or b''
        if not raw:
            return ''
        name = (item.name or '').lower()
        mime = (item.mime_type or '').lower()
        try:
            if name.endswith('.pdf') or mime == 'application/pdf':
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw))
                return '\n'.join((page.extract_text() or '') for page in reader.pages)
            if name.endswith(('.docx', '.pptx', '.xlsx')):
                chunks = []
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    names = archive.namelist()
                    if name.endswith('.docx'):
                        wanted = [n for n in names if n == 'word/document.xml' or n.startswith('word/header') or n.startswith('word/footer')]
                    elif name.endswith('.pptx'):
                        wanted = [n for n in names if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
                    else:
                        wanted = [n for n in names if n == 'xl/sharedStrings.xml' or (n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))]
                    for part in wanted:
                        text = archive.read(part).decode('utf-8', errors='ignore')
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = re.sub(r'\s+', ' ', text).strip()
                        if text:
                            chunks.append(text)
                return '\n'.join(chunks)
            if mime.startswith('text/') or name.endswith(('.txt', '.csv', '.md', '.json')):
                return raw.decode('utf-8', errors='ignore')
        except Exception:
            app.logger.exception('Falha ao extrair texto do anexo de reunião %s', item.id)
        return ''

    @app.route('/api/meeting/audio-sessions/<session_id>/attachments', methods=['GET', 'POST'])
    @app_module.login_required
    def meeting_attachments(session_id):
        session = _session_or_404(session_id)
        user = app_module.current_user()
        if not _can_view_project(user, session.project_id):
            abort(403)
        state = db.session.get(app_module.AppState, 1)
        payload = state.payload if state else {}
        meeting = _saved_meeting(payload, session_id, session.project_id)
        if not meeting:
            return jsonify({'error': 'Salve a reunião antes de anexar arquivos.'}), 409

        if request.method == 'POST':
            app_module.require_csrf()
            if not app_module.can_edit_project(user, session.project_id):
                abort(403)
            f = request.files.get('file')
            if not f or not f.filename:
                return jsonify({'error': 'Selecione um arquivo.'}), 400
            raw = f.read()
            if not raw:
                return jsonify({'error': 'Arquivo vazio.'}), 400
            if len(raw) > 20 * 1024 * 1024:
                return jsonify({'error': 'O arquivo excede 20 MB.'}), 413
            item = MeetingAttachment(
                session_id=session_id,
                project_id=session.project_id,
                name=secure_filename(f.filename) or 'arquivo',
                mime_type=f.mimetype or 'application/octet-stream',
                size=len(raw),
                file_data=raw,
                uploaded_by=user.display_name,
            )
            db.session.add(item)
            db.session.commit()

        rows = MeetingAttachment.query.filter_by(session_id=session_id).order_by(MeetingAttachment.created_at.asc(), MeetingAttachment.id.asc()).all()
        return jsonify({'attachments': [_meeting_attachment_payload(item) for item in rows]})

    @app.route('/api/meeting/attachments/<int:attachment_id>/download')
    @app_module.login_required
    def download_meeting_attachment(attachment_id):
        item = db.session.get(MeetingAttachment, attachment_id)
        if not item:
            abort(404)
        if not _can_view_project(app_module.current_user(), item.project_id):
            abort(403)
        return Response(
            item.file_data,
            mimetype=item.mime_type or 'application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{item.name}"'},
        )

    @app.route('/api/projects/<project_id>/meeting-attachments')
    @app_module.login_required
    def project_meeting_attachments(project_id):
        user = app_module.current_user()
        if not _can_view_project(user, project_id):
            abort(403)
        rows = MeetingAttachment.query.filter_by(project_id=project_id).order_by(MeetingAttachment.created_at.desc(), MeetingAttachment.id.desc()).all()
        sessions = {
            row.id: row for row in MeetingAudioSession.query.filter(
                MeetingAudioSession.id.in_([x.session_id for x in rows])
            ).all()
        } if rows else {}
        return jsonify({'attachments': [{
            **_meeting_attachment_payload(item),
            'sessionId': item.session_id,
            'meetingDate': sessions.get(item.session_id).started_at.isoformat() if sessions.get(item.session_id) and sessions.get(item.session_id).started_at else '',
        } for item in rows]})

    @app.route('/api/meeting/audio-sessions/<session_id>/commitment', methods=['POST'])
    @app_module.login_required
    def update_meeting_commitment(session_id):
        app_module.require_csrf()
        session = _session_or_404(session_id)
        user = app_module.current_user()
        if not app_module.can_edit_project(user, session.project_id):
            abort(403)
        body = request.get_json(force=True) or {}
        state = _load_state_locked()
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        project = app_module.find_project(payload, session.project_id)
        meeting = _saved_meeting(payload, session_id, session.project_id)
        if not project or not meeting:
            return jsonify({'error': 'Reunião salva não encontrada.'}), 404
        commitment = (body.get('commitment') or '').strip()
        meeting['nextWeek'] = commitment
        meeting['commitmentUpdatedAt'] = app_module.now_iso()
        meeting['commitmentUpdatedBy'] = user.display_name
        _sync_meeting_commitment(project, meeting, commitment, user)
        _touch(state, user, payload)
        return jsonify({'ok': True, 'commitment': commitment, 'revision': state.revision})

    @app.route('/api/meeting/ai-status')
    @app_module.login_required
    def meeting_ai_status():
        return jsonify({
            'configured': bool(os.environ.get('OPENAI_API_KEY')),
            'transcribeModel': os.environ.get('MEETING_TRANSCRIBE_MODEL', 'gpt-transcribe'),
            'summaryModel': os.environ.get('MEETING_SUMMARY_MODEL', 'gpt-5.6-luna'),
        })

    @app.route('/api/meeting/audio-sessions', methods=['POST'])
    @app_module.login_required
    def create_meeting_audio_session():
        app_module.require_csrf()
        body = request.get_json(force=True) or {}
        project_id = (body.get('projectId') or '').strip()
        user = app_module.current_user()
        if not project_id or not app_module.can_edit_project(user, project_id):
            abort(403)
        state = db.session.get(app_module.AppState, 1)
        _project_or_404(state, project_id)
        row = MeetingAudioSession(
            id=secrets.token_hex(16),
            project_id=project_id,
            created_by=user.display_name,
            status='recording',
        )
        db.session.add(row)
        db.session.commit()
        return jsonify({'id': row.id, 'projectId': row.project_id, 'startedAt': row.started_at.isoformat()})

    @app.route('/api/meeting/audio-sessions', methods=['GET'])
    @app_module.login_required
    def list_meeting_audio_sessions():
        user = app_module.current_user()
        sessions = MeetingAudioSession.query.order_by(MeetingAudioSession.started_at.desc()).all()
        visible = [s for s in sessions if _can_view_project(user, s.project_id)]
        ids = [s.id for s in visible]
        segments = MeetingAudioSegment.query.filter(MeetingAudioSegment.session_id.in_(ids)).order_by(MeetingAudioSegment.position).all() if ids else []
        counts = {}
        for segment in segments:
            info = counts.setdefault(segment.session_id, {'segments': 0, 'transcribed': 0})
            info['segments'] += 1
            info['transcribed'] += bool(segment.transcript)
        return jsonify({'sessions': [{
            'id': s.id,
            'projectId': s.project_id,
            'createdBy': s.created_by,
            'status': s.status,
            'startedAt': s.started_at.isoformat() if s.started_at else '',
            'endedAt': s.ended_at.isoformat() if s.ended_at else '',
            **counts.get(s.id, {'segments': 0, 'transcribed': 0}),
        } for s in visible if counts.get(s.id, {}).get('segments', 0)]})

    def _session_or_404(session_id):
        row = db.session.get(MeetingAudioSession, session_id)
        if not row:
            abort(404)
        return row

    @app.route('/api/meeting/audio-sessions/<session_id>/segments', methods=['POST', 'GET'])
    @app_module.login_required
    def meeting_audio_segments(session_id):
        session = _session_or_404(session_id)
        user = app_module.current_user()
        if not _can_view_project(user, session.project_id):
            abort(403)

        if request.method == 'POST':
            app_module.require_csrf()
            if not app_module.can_edit_project(user, session.project_id):
                abort(403)
            try:
                position = int(request.form.get('position', '0'))
            except ValueError:
                return jsonify({'error': 'Posição de segmento inválida.'}), 400
            f = request.files.get('file')
            if not f:
                return jsonify({'error': 'Segmento de áudio não recebido.'}), 400
            raw = f.read()
            if not raw:
                return jsonify({'error': 'Segmento de áudio vazio.'}), 400
            if len(raw) > 12 * 1024 * 1024:
                return jsonify({'error': 'Um bloco de áudio excedeu 12 MB. Reduza o tempo do bloco.'}), 413
            existing = MeetingAudioSegment.query.filter_by(session_id=session_id, position=position).first()
            if existing:
                existing.mime_type = f.mimetype or existing.mime_type
                existing.size = len(raw)
                existing.file_data = raw
            else:
                db.session.add(MeetingAudioSegment(
                    session_id=session_id,
                    position=position,
                    mime_type=f.mimetype or 'audio/webm',
                    size=len(raw),
                    file_data=raw,
                ))
            db.session.commit()

        rows = MeetingAudioSegment.query.filter_by(session_id=session_id).order_by(MeetingAudioSegment.position).all()
        return jsonify({'sessionId': session_id, 'projectId': session.project_id, 'segments': [{
            'position': r.position,
            'size': r.size,
            'mimeType': r.mime_type,
            'transcribed': bool(r.transcript),
            'transcript': r.transcript or '',
            'url': f'/api/meeting/audio-sessions/{session_id}/segments/{r.position}/audio',
        } for r in rows]})

    @app.route('/api/meeting/audio-sessions/<session_id>/finish', methods=['POST'])
    @app_module.login_required
    def finish_meeting_audio_session(session_id):
        app_module.require_csrf()
        session = _session_or_404(session_id)
        user = app_module.current_user()
        if not app_module.can_edit_project(user, session.project_id):
            abort(403)
        session.status = 'recorded'
        session.ended_at = datetime.utcnow()
        db.session.commit()
        count = MeetingAudioSegment.query.filter_by(session_id=session_id).count()
        return jsonify({'ok': True, 'segments': count})

    @app.route('/api/meeting/audio-sessions/<session_id>/segments/<int:position>/audio')
    @app_module.login_required
    def meeting_segment_audio(session_id, position):
        session = _session_or_404(session_id)
        if not _can_view_project(app_module.current_user(), session.project_id):
            abort(403)
        seg = MeetingAudioSegment.query.filter_by(session_id=session_id, position=position).first()
        if not seg:
            abort(404)
        return Response(seg.file_data, mimetype=seg.mime_type or 'audio/webm')

    def _transcribe_segment(seg):
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise RuntimeError('ai_not_configured')
        response = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (f'parte_{seg.position}.webm', seg.file_data, seg.mime_type or 'audio/webm')},
            data={
                'model': os.environ.get('MEETING_TRANSCRIBE_MODEL', 'gpt-transcribe'),
                'language': 'pt',
            },
            timeout=180,
        )
        if response.status_code >= 400:
            app.logger.error('Falha na transcrição da parte %s: %s', seg.position, response.text[:1000])
            raise RuntimeError('transcription_failed')
        text = (response.json().get('text') or '').strip()
        if not text:
            raise RuntimeError('empty_transcription')
        seg.transcript = text
        db.session.commit()
        return text

    @app.route('/api/meeting/audio-sessions/<session_id>/segments/<int:position>/transcribe', methods=['POST'])
    @app_module.login_required
    def transcribe_meeting_segment(session_id, position):
        app_module.require_csrf()
        session = _session_or_404(session_id)
        user = app_module.current_user()
        if not app_module.can_edit_project(user, session.project_id):
            abort(403)
        if not os.environ.get('OPENAI_API_KEY'):
            return jsonify({'configured': False, 'error': 'A IA de reunião ainda não possui credencial configurada no servidor.'}), 503
        seg = MeetingAudioSegment.query.filter_by(session_id=session_id, position=position).first()
        if not seg:
            abort(404)
        if seg.transcript:
            return jsonify({'transcript': seg.transcript, 'cached': True})
        try:
            return jsonify({'transcript': _transcribe_segment(seg), 'cached': False})
        except RuntimeError as exc:
            code = str(exc)
            if code == 'transcription_failed':
                return jsonify({'error': 'Falha ao transcrever este bloco de áudio.'}), 502
            if code == 'empty_transcription':
                return jsonify({'error': 'Este bloco não produziu transcrição.'}), 422
            raise

    def _extract_response_text(payload):
        for item in payload.get('output', []) or []:
            if item.get('type') == 'message':
                for part in item.get('content', []) or []:
                    if part.get('type') == 'output_text' and part.get('text'):
                        return part['text']
        return ''

    @app.route('/api/meeting/summarize', methods=['POST'])
    @app_module.login_required
    def summarize_meeting():
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
        project = _project_or_404(state, project_id)
        meeting = _saved_meeting(state.payload if state else {}, session_id, project_id) if session_id else None
        if session_id and not meeting:
            return jsonify({'error': 'Salve a reunião antes de gerar o documento.'}), 409

        if not transcript and session_id:
            rows = MeetingAudioSegment.query.filter_by(session_id=session_id).order_by(MeetingAudioSegment.position).all()
            transcript = '\n\n'.join((r.transcript or '').strip() for r in rows if (r.transcript or '').strip())
        if not transcript:
            return jsonify({'error': 'A reunião ainda não possui transcrição suficiente para gerar o documento.'}), 400

        attachment_context = []
        if session_id:
            attachments = MeetingAttachment.query.filter_by(session_id=session_id).order_by(MeetingAttachment.id).all()
            remaining = 80000
            for item in attachments[:10]:
                text = _extract_meeting_attachment_text(item).strip()
                if not text:
                    continue
                text = text[:remaining]
                if not text:
                    break
                attachment_context.append(f'ARQUIVO: {item.name}\n{text}')
                remaining -= len(text)
                if remaining <= 0:
                    break

        commitment = ((meeting or {}).get('nextWeek') or '').strip()
        docs = '\n\n'.join(attachment_context)
        prompt = f"""Você é o secretário executivo da Transformação KAZ.
Gere UM ÚNICO DOCUMENTO DE REUNIÃO, em português, sintetizando a reunião do projeto {project.get('name') or project_id}.

Regras:
- Não invente fatos, nomes, responsáveis, prazos, decisões ou compromissos.
- Não devolva JSON e não divida a resposta em campos fixos como "tópicos", "decisões", "próximos passos" ou "dependências".
- Escreva um documento executivo coeso, claro e objetivo, com parágrafos e listas somente quando ajudarem a leitura.
- Registre no próprio texto o que foi discutido, o que efetivamente ficou definido e os encaminhamentos sustentados pela reunião.
- O compromisso da próxima reunião é informado manualmente pela pessoa e NÃO deve ser criado pela IA. Se houver compromisso oficial abaixo, você pode mencioná-lo como compromisso já registrado.
- Considere os arquivos apresentados quando houver conteúdo extraível e útil. Não trate um arquivo como decisão da reunião sem evidência na conversa.

COMPROMISSO OFICIAL INFORMADO MANUALMENTE:
{commitment or 'Não informado até o momento.'}

TRANSCRIÇÃO:
{transcript}

ARQUIVOS APRESENTADOS:
{docs or 'Nenhum arquivo com texto extraível foi anexado.'}
"""
        try:
            response = requests.post(
                'https://api.openai.com/v1/responses',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': os.environ.get('MEETING_SUMMARY_MODEL', 'gpt-5.6-luna'),
                    'input': prompt,
                },
                timeout=240,
            )
            if response.status_code >= 400:
                app.logger.error('Falha no documento IA: %s', response.text[:1000])
                return jsonify({'error': 'A gravação e os anexos foram preservados, mas a IA não conseguiu gerar o documento da reunião.'}), 502
            summary = _extract_response_text(response.json()).strip()
            if not summary:
                return jsonify({'error': 'A IA não retornou conteúdo para o documento da reunião.'}), 502

            if meeting and session_id:
                state = _load_state_locked()
                payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                saved = _saved_meeting(payload, session_id, project_id)
                if not saved:
                    return jsonify({'error': 'Reunião salva não encontrada.'}), 404
                saved['summary'] = summary
                saved['transcript'] = transcript
                saved['aiProcessed'] = True
                saved['aiProcessedAt'] = app_module.now_iso()
                saved['aiProcessedBy'] = user.display_name
                _touch(state, user, payload)
                return jsonify({'configured': True, 'summary': summary, 'aiProcessed': True, 'revision': state.revision})

            return jsonify({'configured': True, 'summary': summary})
        except requests.RequestException:
            app.logger.exception('Falha de comunicação com a IA da reunião')
            return jsonify({'error': 'Falha de comunicação com a IA da reunião.'}), 502

    @app.route('/api/meeting/audio-sessions/<session_id>/manifest')
    @app_module.login_required
    def meeting_audio_manifest(session_id):
        session = _session_or_404(session_id)
        if not _can_view_project(app_module.current_user(), session.project_id):
            abort(403)
        rows = MeetingAudioSegment.query.filter_by(session_id=session_id).order_by(MeetingAudioSegment.position).all()
        return jsonify({
            'id': session.id,
            'projectId': session.project_id,
            'status': session.status,
            'startedAt': session.started_at.isoformat() if session.started_at else '',
            'endedAt': session.ended_at.isoformat() if session.ended_at else '',
            'segments': [{
                'position': r.position,
                'size': r.size,
                'url': f'/api/meeting/audio-sessions/{session_id}/segments/{r.position}/audio',
            } for r in rows],
        })

    @app_module.login_required
    def create_meeting_v2():
        app_module.require_csrf()
        body = request.get_json(force=True) or {}
        user = app_module.current_user()
        project_id = (body.get('projectId') or '').strip()
        if not app_module.can_edit_project(user, project_id):
            abort(403)
        state = _load_state_locked()
        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        project = app_module.find_project(payload, project_id)
        if not project:
            abort(404)
        session_id = (body.get('audioSessionId') or '').strip()
        if session_id:
            session = db.session.get(MeetingAudioSession, session_id)
            if not session or session.project_id != project_id:
                return jsonify({'error': 'Gravação não encontrada neste projeto.'}), 400
        previous_review = body.get('previousReview')
        if not isinstance(previous_review, dict):
            previous_review = {
                'commitments': [{
                    'text': c.get('text') or '',
                    'status': c.get('status') or 'Aberto',
                    'author': c.get('author') or '',
                    'createdAt': c.get('createdAt') or '',
                } for c in (project.get('weeklyCommitments') or []) if c.get('status') in ('Aberto','Parcial','Realizado','Não realizado')],
                'dependencies': [{
                    'subject': d.get('subject') or d.get('title') or '',
                    'status': d.get('status') or '',
                    'director': d.get('director') or d.get('assignedDirector') or '',
                    'deadline': d.get('deadline') or '',
                } for d in (payload.get('dependencies') or []) if d.get('projectId') == project_id and d.get('status') != 'Resolvida'],
                'capturedAt': app_module.now_iso(),
            }
        existing = next((m for m in payload.get('meetings', []) if session_id and m.get('audioSessionId') == session_id and m.get('projectId') == project_id), None)
        if existing:
            for key in ('notes', 'topics', 'decisions', 'nextSteps', 'transcript', 'summary', 'dependencies'):
                if key in body:
                    existing[key] = (body.get(key) or '').strip()
            if 'nextWeek' in body:
                existing['nextWeek'] = (body.get('nextWeek') or '').strip()
                _sync_meeting_commitment(project, existing, existing['nextWeek'], user)
            existing['audioSegments'] = MeetingAudioSegment.query.filter_by(session_id=session_id).count()
            if 'aiProcessed' in body:
                existing['aiProcessed'] = bool(body.get('aiProcessed'))
            existing['previousReview'] = previous_review
            _touch(state, user, payload)
            return jsonify({'ok': True, 'meeting': existing, 'revision': state.revision})

        meeting = {
            'id': secrets.token_hex(7),
            'projectId': project_id,
            'at': app_module.now_iso(),
            'createdBy': user.display_name,
            'notes': (body.get('notes') or '').strip(),
            'topics': (body.get('topics') or '').strip(),
            'decisions': (body.get('decisions') or '').strip(),
            'nextSteps': (body.get('nextSteps') or '').strip(),
            'nextWeek': (body.get('nextWeek') or '').strip(),
            'transcript': (body.get('transcript') or '').strip(),
            'summary': (body.get('summary') or '').strip(),
            'dependencies': (body.get('dependencies') or '').strip(),
            'audioSessionId': session_id,
            'audioSegments': MeetingAudioSegment.query.filter_by(session_id=session_id).count() if session_id else 0,
            'aiProcessed': bool(body.get('aiProcessed')),
            'previousReview': previous_review,
            'savedAt': app_module.now_iso(),
        }
        payload.setdefault('meetings', []).append(meeting)
        project['lastUpdate'] = app_module.now_iso()
        _sync_meeting_commitment(project, meeting, meeting['nextWeek'], user)
        _touch(state, user, payload)
        return jsonify({'ok': True, 'meeting': meeting, 'revision': state.revision})

    app.view_functions['create_meeting'] = create_meeting_v2
