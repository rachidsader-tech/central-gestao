import json
import os
import struct
import threading
import time
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


def _read_vint(data, pos):
    if pos >= len(data):
        return None, 0
    first = data[pos]
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8 or pos + length > len(data):
        return None, 0
    value = first & (mask - 1)
    for i in range(1, length):
        value = (value << 8) | data[pos + i]
    return value, length


def _webm_duration_seconds(raw):
    if not raw:
        return None
    head = raw[:min(len(raw), 2 * 1024 * 1024)]
    scale = 1_000_000

    i = head.find(b'\x2a\xd7\xb1')
    if i >= 0:
        size, n = _read_vint(head, i + 3)
        if size and n and i + 3 + n + size <= len(head) and size <= 8:
            scale = int.from_bytes(head[i + 3 + n:i + 3 + n + size], 'big') or scale

    i = head.find(b'\x44\x89')
    if i >= 0:
        size, n = _read_vint(head, i + 2)
        if size in (4, 8) and n and i + 2 + n + size <= len(head):
            chunk = head[i + 2 + n:i + 2 + n + size]
            try:
                duration_ticks = struct.unpack('>f' if size == 4 else '>d', chunk)[0]
                seconds = float(duration_ticks) * float(scale) / 1_000_000_000.0
                if 0.5 <= seconds <= 12 * 3600:
                    return seconds
            except Exception:
                pass
    return None


def _fallback_duration_seconds(size_bytes):
    # Browser MediaRecorder antigo costumava ficar perto de 128 kbps.
    if not size_bytes:
        return None
    return max(1.0, min(6 * 3600.0, (float(size_bytes) * 8.0) / 128000.0))


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

    with app.app_context():
        state = db.session.get(app_module.AppState, 1)
        if not state:
            app.logger.error('Legacy meeting migration skipped: app state missing.')
            return

        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
        changed = False

        meetings_by_id = {m.get('id'): m for m in payload.get('meetings', [])}

        for spec in LEGACY_MEETINGS:
            meeting = meetings_by_id.get(spec['meeting_id'])
            if not meeting:
                app.logger.warning('Legacy meeting not found: %s', spec['meeting_id'])
                continue

            session_id = f"legacy_{spec['meeting_id']}"
            existing = db.session.execute(
                text("SELECT id FROM kaz_meeting_audio_sessions WHERE id=:id"),
                {'id': session_id}
            ).first()

            meeting_at = _parse_iso(meeting.get('at')) or datetime.utcnow()
            created_by = meeting.get('createdBy') or 'Rachid'
            attachment = db.session.get(app_module.Attachment, spec['attachment_id']) if spec['attachment_id'] else None

            if attachment and attachment.file_data:
                duration = _webm_duration_seconds(attachment.file_data)
                if not duration:
                    duration = _fallback_duration_seconds(attachment.size)
                ended_at = attachment.created_at or meeting_at
                started_at = ended_at - timedelta(seconds=float(duration or 0))
            else:
                started_at = meeting_at
                ended_at = meeting_at

            if not existing:
                db.session.execute(text("""
                    INSERT INTO kaz_meeting_audio_sessions
                        (id, project_id, created_by, status, started_at, ended_at, created_at)
                    VALUES
                        (:id, :project_id, :created_by, 'recorded', :started_at, :ended_at, :created_at)
                """), {
                    'id': session_id,
                    'project_id': spec['project_id'],
                    'created_by': created_by,
                    'started_at': started_at,
                    'ended_at': ended_at,
                    'created_at': ended_at,
                })

            if attachment and attachment.file_data:
                segment_exists = db.session.execute(text("""
                    SELECT id FROM kaz_meeting_audio_segments
                     WHERE session_id=:session_id AND position=0
                """), {'session_id': session_id}).first()
                if not segment_exists:
                    db.session.execute(text("""
                        INSERT INTO kaz_meeting_audio_segments
                            (session_id, position, mime_type, size, file_data, transcript, created_at)
                        VALUES
                            (:session_id, 0, :mime_type, :size, :file_data, '', :created_at)
                    """), {
                        'session_id': session_id,
                        'mime_type': attachment.mime_type or 'audio/webm',
                        'size': attachment.size or len(attachment.file_data),
                        'file_data': attachment.file_data,
                        'created_at': attachment.created_at or ended_at,
                    })

            if meeting.get('audioSessionId') != session_id:
                meeting['audioSessionId'] = session_id
                meeting['audioSegments'] = 1 if attachment and attachment.file_data else 0
                meeting['legacyMigrated'] = True
                changed = True

        if changed:
            state.payload = payload
            state.revision = int(state.revision or 0) + 1
            state.updated_by = 'Sistema · migração de reuniões históricas'
            state.updated_at = datetime.utcnow()

        db.session.commit()
        app.logger.info('Legacy meeting migration complete: 6 records linked to meeting archive.')

    def _run_ai_validation():
        # Validação real nas gravações recuperadas. Não altera o conteúdo oficial da reunião.
        with app.app_context():
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                app.logger.warning('Legacy AI validation skipped: OPENAI_API_KEY missing.')
                return

            for spec in [x for x in LEGACY_MEETINGS if x['attachment_id']]:
                meeting_id = spec['meeting_id']
                session_id = f"legacy_{meeting_id}"
                try:
                    state = db.session.get(app_module.AppState, 1)
                    payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                    meeting = next((m for m in payload.get('meetings', []) if m.get('id') == meeting_id), None)
                    if not meeting:
                        continue
                    if meeting.get('migrationAiPreview') and meeting['migrationAiPreview'].get('status') == 'success':
                        app.logger.info('Legacy AI validation already complete: %s', meeting_id)
                        continue

                    seg = db.session.execute(text("""
                        SELECT id, mime_type, file_data, transcript
                          FROM kaz_meeting_audio_segments
                         WHERE session_id=:session_id AND position=0
                    """), {'session_id': session_id}).mappings().first()
                    if not seg or not seg['file_data']:
                        continue

                    transcript = (seg['transcript'] or '').strip()
                    if not transcript:
                        app.logger.info('Legacy AI validation transcribing %s (%s)', meeting_id, spec['project_id'])
                        response = requests.post(
                            'https://api.openai.com/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {api_key}'},
                            files={'file': (f'{session_id}.webm', seg['file_data'], seg['mime_type'] or 'audio/webm')},
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
                            UPDATE kaz_meeting_audio_segments
                               SET transcript=:transcript
                             WHERE id=:id
                        """), {'transcript': transcript, 'id': seg['id']})
                        db.session.commit()

                    project_name = next((p.get('name') for p in payload.get('projects', []) if p.get('id') == spec['project_id']), spec['project_id'])
                    prompt = f"""Você é o secretário executivo da Transformação KAZ.
Analise a transcrição de uma reunião histórica do projeto {project_name}.
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
                    app.logger.info('Legacy AI validation summarizing %s (%s)', meeting_id, spec['project_id'])
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
                    if not meeting:
                        continue
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
                    state.updated_by = 'Sistema · teste IA reuniões históricas'
                    state.updated_at = datetime.utcnow()
                    db.session.commit()
                    app.logger.info('Legacy AI validation SUCCESS: %s (%s)', meeting_id, spec['project_id'])

                    # Pequeno intervalo para não disparar as quatro chamadas de forma agressiva.
                    time.sleep(1)
                except Exception as exc:
                    db.session.rollback()
                    app.logger.exception('Legacy AI validation FAILED: %s (%s): %s', meeting_id, spec['project_id'], exc)
                    try:
                        state = db.session.execute(
                            app_module.select(app_module.AppState).where(app_module.AppState.id == 1).with_for_update()
                        ).scalar_one()
                        payload = json.loads(json.dumps(state.payload, ensure_ascii=False))
                        meeting = next((m for m in payload.get('meetings', []) if m.get('id') == meeting_id), None)
                        if meeting:
                            meeting['migrationAiPreview'] = {
                                'status': 'failed',
                                'testedAt': app_module.now_iso(),
                                'error': str(exc)[:500],
                            }
                            state.payload = payload
                            state.revision = int(state.revision or 0) + 1
                            state.updated_by = 'Sistema · teste IA reuniões históricas'
                            state.updated_at = datetime.utcnow()
                            db.session.commit()
                    except Exception:
                        db.session.rollback()

    # Executa depois do boot, sem bloquear a subida do serviço.
    thread = threading.Thread(target=_run_ai_validation, name='legacy-meeting-ai-validation', daemon=True)
    thread.start()
