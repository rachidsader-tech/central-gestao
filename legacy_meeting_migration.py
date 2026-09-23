import os, json, hashlib
from datetime import datetime, timedelta, timezone
import psycopg

DB_URL = os.environ.get('DATABASE_URL')
MARKER = 'legacy-meetings-2026-09-16-v2'

SPECS = [
    {'meeting_id':'9d199bca081bc3','project_id':'comercial','attachment_id':1},
    {'meeting_id':'4c560303757c14','project_id':'posvenda','attachment_id':34},
    {'meeting_id':'4154a21c6cbd1e','project_id':'compras','attachment_id':35},
    {'meeting_id':'805a1612789949','project_id':'planejamento','attachment_id':None},
    {'meeting_id':'b7988848569918','project_id':'financeiro','attachment_id':36},
    {'meeting_id':'a138510ca18088','project_id':'producao','attachment_id':None},
]

def parse_iso(value):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()

def estimated_duration(size_bytes):
    if not size_bytes:
        return 0
    return max(1, int((int(size_bytes) * 8) / 128000))

def main():
    if not DB_URL:
        print('Legacy meeting migration skipped: DATABASE_URL missing.', flush=True)
        return

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload, revision FROM kaz_app_state WHERE id=1 FOR UPDATE")
            row = cur.fetchone()
            if not row:
                raise RuntimeError('kaz_app_state row 1 not found')
            payload, revision = row
            if isinstance(payload, str):
                payload = json.loads(payload)

            meetings = payload.get('meetings') or []
            by_id = {m.get('id'): m for m in meetings}
            missing = [s['meeting_id'] for s in SPECS if s['meeting_id'] not in by_id]
            if missing:
                raise RuntimeError(f'Legacy meetings missing from state: {missing}')

            # Backup lógico dos seis registros antes de vinculá-los ao novo arquivo de reuniões.
            try:
                cur.execute("SELECT to_regclass('public.central_migration_backups')")
                has_backup_table = bool(cur.fetchone()[0])
            except Exception:
                has_backup_table = False
            if has_backup_table:
                cur.execute("SELECT 1 FROM central_migration_backups WHERE backup_key=%s", (MARKER,))
                if not cur.fetchone():
                    snapshot = {'meetings':[by_id[s['meeting_id']] for s in SPECS]}
                    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',',':'))
                    checksum = hashlib.sha256(raw.encode('utf-8')).hexdigest()
                    cur.execute(
                        "INSERT INTO central_migration_backups (backup_key,payload,checksum,created_at) VALUES (%s,CAST(%s AS json),%s,NOW())",
                        (MARKER, raw, checksum),
                    )

            migrated = 0
            for spec in SPECS:
                meeting = by_id[spec['meeting_id']]
                session_id = 'legacy_' + spec['meeting_id']
                created_by = meeting.get('createdBy') or 'Rachid'
                meeting_at = parse_iso(meeting.get('at'))

                attachment = None
                if spec['attachment_id']:
                    cur.execute(
                        "SELECT id,mime_type,size,created_at FROM kaz_attachments WHERE id=%s",
                        (spec['attachment_id'],),
                    )
                    attachment = cur.fetchone()

                if attachment:
                    att_id, mime_type, size, ended_at = attachment
                    ended_at = ended_at or meeting_at
                    started_at = ended_at - timedelta(seconds=estimated_duration(size))
                else:
                    att_id = None
                    mime_type = None
                    size = 0
                    started_at = meeting_at
                    ended_at = meeting_at

                cur.execute(
                    """
                    INSERT INTO kaz_meeting_audio_sessions
                        (id,project_id,created_by,status,started_at,ended_at,created_at)
                    VALUES (%s,%s,%s,'recorded',%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (session_id, spec['project_id'], created_by, started_at, ended_at, ended_at),
                )

                if att_id:
                    cur.execute(
                        """
                        INSERT INTO kaz_meeting_audio_segments
                            (session_id,position,mime_type,size,file_data,transcript,created_at)
                        SELECT %s,0,COALESCE(mime_type,'audio/webm'),size,file_data,'',created_at
                          FROM kaz_attachments
                         WHERE id=%s
                           AND NOT EXISTS (
                               SELECT 1 FROM kaz_meeting_audio_segments
                                WHERE session_id=%s AND position=0
                           )
                        """,
                        (session_id, att_id, session_id),
                    )

                if meeting.get('audioSessionId') != session_id or not meeting.get('legacyMigrated'):
                    meeting['audioSessionId'] = session_id
                    meeting['audioSegments'] = 1 if att_id else 0
                    meeting['legacyMigrated'] = True
                    meeting['legacyAudioAvailable'] = bool(att_id)
                    migrated += 1

            payload['meetings'] = meetings
            cur.execute(
                """
                UPDATE kaz_app_state
                   SET payload=CAST(%s AS json),
                       revision=%s,
                       updated_by=%s,
                       updated_at=NOW()
                 WHERE id=1
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    int(revision or 0) + (1 if migrated else 0),
                    'Sistema · migração de reuniões históricas' if migrated else 'Sistema',
                ),
            )
        conn.commit()

    print(f'Legacy meeting migration complete: 6 meetings linked, {migrated} state records updated.', flush=True)

if __name__ == '__main__':
    main()
