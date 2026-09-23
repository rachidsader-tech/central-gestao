import json
import os
import threading
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text


LEGACY_MEETINGS = [
    {'meeting_id': '9d199bca081bc3', 'project_id': 'comercial', 'attachment_id': 1},
    {'meeting_id': '4c560303757c14', 'project_id': 'posvenda', 'attachment_id': 34},
    {'meeting_id': '4154a21c6cbd1e', 'project_id': 'compras', 'attachment_id': 35},
    {'meeting_id': '805a1612789949', 'project_id': 'planejamento', 'attachment_id': None},
    {'meeting_id': 'b7988848569918', 'project_id': 'financeiro', 'attachment_id': 36},
    {'meeting_id': 'a138510ca18088', 'project_id': 'producao', 'attachment_id': None},
]


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _estimated_duration_seconds(size_bytes):
    if not size_bytes:
        return 0
    # Estimativa conservadora para os WebM antigos gravados pelo navegador.
    return max(1, int((int(size_bytes) * 8) / 128000))


def _extract_response_text(payload):
    for item in payload.get('output', []) or []:
        if item.get('type') == 'message':
            for part in item.get('content', []) or []:
                if part.get('type') == 'output_text' and part.get('text'):
                    return part['text']
    return ''


def register(app_module):
    app = app_module.app
    db = app_module.db

    try:
        with app.app_context():
            state = db.session.get(app_module.AppState, 1)
            if not state:
                app.logger.error('Legacy meeting migration skipped: app state missing.')
                return

            payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
            meetings_by_id = {m.get('id'): m for m in payload.get('meetings', [])}
            changed = False

            for spec in LEGACY_MEETINGS:
                meeting = meetings_by_id.get(spec['meeting_id'])
                if not meeting:
                    app.logger.warning('Legacy meeting not found: %s', spec['meeting_id'])
                    continue

                session_id = f"legacy_{spec['meeting_id']}"
                meeting_at = _parse_iso(meeting.get('at')) or datetime.utcnow()
                created_by = meeting.get('createdBy') or 'Rachid'

                attachment = None
                if spec['attachment_id']:
                    attachment = db.session.execute(text("""
                        SELECT id, mime_type, size, created_at
                          FROM kaz_attachments
                         WHERE id=:id
                    """), {'id': spec['attachment_id']}).mappings().first()

                if attachment:
                    ended_at = attachment['created_at'] or meeting_at
                    started_at = ended_at - timedelta(seconds=_estimated_duration_seconds(attachment['size']))
                else:
                    started_at = meeting_at
                    ended_at = meeting_at

                db.session.execute(text("""
                    INSERT INTO kaz_meeting_audio_sessions
                        (id, project_id, created_by, status, started_at, ended_at, created_at)
                    VALUES
                        (:id, :project_id, :created_by, 'recorded', :started_at, :ended_at, :created_at)
                    ON CONFLICT (id) DO NOTHING
                """), {
                    'id': session_id,
                    'project_id': spec['project_id'],
                    'created_by': created_by,
                    'started_at': started_at,
                    'ended_at': ended_at,
                    'created_at': ended_at,
                })

                if attachment:
                    # Copia o BYTEA dentro do próprio PostgreSQL, sem trafegar arquivos grandes pelo app.
                    db.session.execute(text("""
                        INSERT INTO kaz_meeting_audio_segments
                            (session_id, position, mime_type, size, file_data, transcript, created_at)
                        SELECT
                            :session_id, 0, COALESCE(mime_type,'audio/webm'), size, file_data, '', created_at
                          FROM kaz_attachments
                         WHERE id=:attachment_id
                           AND NOT EXISTS (
                               SELECT 1 FROM kaz_meeting_audio_segments
                                WHERE session_id=:session_id AND position=0
                           )
                    """), {
                        'session_id': session_id,
                        'attachment_id': spec['attachment_id'],
                    })

                if meeting.get('audioSessionId') != session_id:
                    meeting['audioSessionId'] = session_id
                    meeting['audioSegments'] = 1 if attachment else 0
                    meeting['legacyMigrated'] = True
                    changed = True

            if changed:
                state.payload = payload
                state.revision = int(state.revision or 0) + 1
                state.updated_by = 'Sistema · migração de reuniões históricas'
                state.updated_at = datetime.utcnow()

            db.session.commit()
            app.logger.info('Legacy meeting migration complete: 6 historical meetings linked.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Legacy meeting migration failed, but app boot will continue.')

    def _validate_ai_on_financeiro():
        # Teste real e controlado em uma gravação migrada pequena (Financeiro).
        # O resultado fica como prévia e não altera o conteúdo oficial da reunião.
        with app.app_context():
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                app.logger.warning('Legacy AI validation skipped: OPENAI_API_KEY missing.')
                return

            meeting_id = 'b7988848569918'
            session_id = f'legacy_{meeting_id}'
            try:
                state = db.session.get(app_module.AppState, 1)
                payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                meeting = next((m for m in payload.get('meetings', []) if m.get('id') == meeting_id), None)
                if not meeting:
                    return
                if meeting.get('migrationAiPreview', {}).get('status') == 'success':
                    app.logger.info('Legacy AI validation already complete: %s', meeting_id)
                    return

                seg = db.session.execute(text("""
                    SELECT id, mime_type, file_data, transcript
                      FROM kaz_meeting_audio_segments
                     WHERE session_id=:session_id AND position=0
                """), {'session_id': session_id}).mappings().first()
                if not seg or not seg['file_data']:
                    app.logger.warning('Legacy AI validation skipped: Financeiro audio missing.')
                    return

                transcript = (seg['transcript'] or '').strip()
                if not transcript:
                    app.logger.info('Legacy AI validation transcribing Financeiro.')
                    response = requests.post(
                        'https://api.openai.com/v1/audio/transcriptions',
                        headers={'Authorization': f'Bearer {api_key}'},
                        files={'file': ('financeiro_2026-09-16.webm', seg['file_data'], seg['mime_type'] or 'audio/webm')},
                        data={
                            'model': os.environ.get('MEETING_TRANSCRIBE_MODEL', 'gpt-transcribe'),
                            'language': 'pt',
                        },
                        timeout=240,
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(f"transcription {response.status_code}: {response.text[:500]}")
                    transcript = (response.json().get('text') or '').strip()
                    if not transcript:
                        raise RuntimeError('transcription empty')
                    db.session.execute(text("""
                        UPDATE kaz_meeting_audio_segments SET transcript=:t WHERE id=:id
                    """), {'t': transcript, 'id': seg['id']})
                    db.session.commit()

                prompt = f"""Você é o secretário executivo da Transformação KAZ.
Analise a transcrição de uma reunião histórica do projeto Financeiro.
Não invente fatos, nomes, responsáveis, prazos, compromissos ou decisões.
Separe claramente o que foi tratado do que foi efetivamente decidido.
Retorne SOMENTE JSON válido, sem markdown, com estas chaves de string:
summary: resumo executivo curto;
topics: principais assuntos tratados, um por linha;
decisions: decisões efetivamente tomadas, um por linha;
next_steps: próximos passos mencionados ou acordados, um por linha;
dependencies: dependências reais da Diretoria, um por linha;
commitment: possível principal compromisso estratégico para a próxima reunião, somente se estiver sustentado pela conversa.
Quando não houver evidência suficiente, use string vazia.

TRANSCRIÇÃO:
{transcript}"""
                app.logger.info('Legacy AI validation summarizing Financeiro.')
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
                    raise RuntimeError(f"summary {response.status_code}: {response.text[:500]}")
                raw = _extract_response_text(response.json()).strip()
                try:
                    structured = json.loads(raw)
                except Exception:
                    structured = {'summary': raw}

                state = db.session.execute(
                    app_module.select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
                ).scalar_one()
                payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                meeting = next((m for m in payload.get('meetings', []) if m.get('id') == meeting_id), None)
                if meeting:
                    meeting['migrationAiPreview'] = {
                        'status': 'success',
                        'testedAt': app_module.now_iso(),
                        'summary': (structured.get('summary') or '').strip(),
                        'topics': (structured.get('topics') or '').strip(),
                        'decisions': (structured.get('decisions') or '').strip(),
                        'nextSteps': (structured.get('next_steps') or '').strip(),
                        'dependencies': (structured.get('dependencies') or '').strip(),
                        'commitment': (structured.get('commitment') or '').strip(),
                    }
                    state.payload = payload
                    state.revision = int(state.revision or 0) + 1
                    state.updated_by = 'Sistema · teste IA reunião histórica'
                    state.updated_at = datetime.utcnow()
                    db.session.commit()
                app.logger.info('Legacy AI validation SUCCESS: Financeiro.')
            except Exception:
                db.session.rollback()
                app.logger.exception('Legacy AI validation FAILED: Financeiro.')

    threading.Thread(
        target=_validate_ai_on_financeiro,
        name='legacy-financeiro-ai-validation',
        daemon=True,
    ).start()
