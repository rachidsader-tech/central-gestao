import os, json, threading, time
import psycopg
import requests

DB_URL = os.environ.get('DATABASE_URL')
MEETING_ID = 'b7988848569918'
SESSION_ID = 'legacy_' + MEETING_ID

def extract_response_text(payload):
    for item in payload.get('output', []) or []:
        if item.get('type') == 'message':
            for part in item.get('content', []) or []:
                if part.get('type') == 'output_text' and part.get('text'):
                    return part['text']
    return ''

def worker():
    time.sleep(2)
    api_key = os.environ.get('OPENAI_API_KEY')
    if not DB_URL or not api_key:
        print('Legacy AI validation skipped: missing DATABASE_URL or OPENAI_API_KEY.', flush=True)
        return
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload,revision FROM kaz_app_state WHERE id=1")
                payload, revision = cur.fetchone()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                meeting = next((m for m in (payload.get('meetings') or []) if m.get('id') == MEETING_ID), None)
                if not meeting:
                    print('Legacy AI validation skipped: Financeiro meeting missing.', flush=True)
                    return
                if (meeting.get('migrationAiPreview') or {}).get('status') == 'success':
                    print('Legacy AI validation already complete: Financeiro.', flush=True)
                    return

                cur.execute(
                    "SELECT id,mime_type,file_data,transcript FROM kaz_meeting_audio_segments WHERE session_id=%s AND position=0",
                    (SESSION_ID,),
                )
                seg = cur.fetchone()
                if not seg:
                    print('Legacy AI validation skipped: migrated Financeiro audio missing.', flush=True)
                    return
                seg_id, mime_type, file_data, transcript = seg
                transcript = (transcript or '').strip()

                if not transcript:
                    print('Legacy AI validation: transcribing Financeiro recording...', flush=True)
                    r = requests.post(
                        'https://api.openai.com/v1/audio/transcriptions',
                        headers={'Authorization':f'Bearer {api_key}'},
                        files={'file':('financeiro_2026-09-16.webm', file_data, mime_type or 'audio/webm')},
                        data={
                            'model':os.environ.get('MEETING_TRANSCRIBE_MODEL','gpt-transcribe'),
                            'language':'pt',
                        },
                        timeout=240,
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(f'transcription {r.status_code}: {r.text[:500]}')
                    transcript = (r.json().get('text') or '').strip()
                    if not transcript:
                        raise RuntimeError('transcription empty')
                    cur.execute("UPDATE kaz_meeting_audio_segments SET transcript=%s WHERE id=%s",(transcript,seg_id))
                    conn.commit()

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

                print('Legacy AI validation: summarizing Financeiro recording...', flush=True)
                r = requests.post(
                    'https://api.openai.com/v1/responses',
                    headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
                    json={'model':os.environ.get('MEETING_SUMMARY_MODEL','gpt-5.6-luna'),'input':prompt},
                    timeout=240,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f'summary {r.status_code}: {r.text[:500]}')
                raw = extract_response_text(r.json()).strip()
                try:
                    structured = json.loads(raw)
                except Exception:
                    structured = {'summary':raw}

                cur.execute("SELECT payload,revision FROM kaz_app_state WHERE id=1 FOR UPDATE")
                payload, revision = cur.fetchone()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                meeting = next((m for m in (payload.get('meetings') or []) if m.get('id') == MEETING_ID), None)
                if not meeting:
                    raise RuntimeError('meeting disappeared during validation')
                meeting['migrationAiPreview'] = {
                    'status':'success',
                    'testedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'summary':(structured.get('summary') or '').strip(),
                    'topics':(structured.get('topics') or '').strip(),
                    'decisions':(structured.get('decisions') or '').strip(),
                    'nextSteps':(structured.get('next_steps') or '').strip(),
                    'dependencies':(structured.get('dependencies') or '').strip(),
                    'commitment':(structured.get('commitment') or '').strip(),
                }
                cur.execute(
                    "UPDATE kaz_app_state SET payload=CAST(%s AS json),revision=%s,updated_by=%s,updated_at=NOW() WHERE id=1",
                    (json.dumps(payload,ensure_ascii=False),int(revision or 0)+1,'Sistema · teste IA reunião histórica'),
                )
                conn.commit()
        print('Legacy AI validation SUCCESS: Financeiro recording transcribed and summarized.', flush=True)
    except Exception as exc:
        print(f'Legacy AI validation FAILED: {exc}', flush=True)

def start():
    threading.Thread(target=worker,name='legacy-ai-validation',daemon=True).start()
