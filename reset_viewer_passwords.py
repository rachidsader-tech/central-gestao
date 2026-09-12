import os, json, hashlib
import psycopg
from werkzeug.security import generate_password_hash

DB_URL = os.environ.get('DATABASE_URL')
TEMP_PASSWORD = os.environ.get('KAZ_VIEWER_TEMP_PASSWORD')
MARKER = 'viewer-temp-password-v1'
VIEWERS = ['julia','michele','kawe','cole','lucas','julio','felipe','lais']

if not DB_URL or not TEMP_PASSWORD:
    print('Viewer password migration skipped: missing environment variable.')
    raise SystemExit(0)

with psycopg.connect(DB_URL) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.central_migration_backups')")
        if not cur.fetchone()[0]:
            raise RuntimeError('central_migration_backups table not found')
        cur.execute("SELECT 1 FROM central_migration_backups WHERE backup_key=%s", (MARKER,))
        if cur.fetchone():
            print('Viewer password migration already applied.')
            raise SystemExit(0)

        password_hash = generate_password_hash(TEMP_PASSWORD)
        cur.execute(
            "UPDATE kaz_users SET password_hash=%s WHERE role='viewer' AND username = ANY(%s)",
            (password_hash, VIEWERS),
        )
        updated = cur.rowcount
        if updated != len(VIEWERS):
            raise RuntimeError(f'Expected {len(VIEWERS)} viewer users, updated {updated}')

        payload = {'action':'temporary_password_set','users':VIEWERS,'count':updated}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        checksum = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        cur.execute(
            "INSERT INTO central_migration_backups (backup_key,payload,checksum,created_at) VALUES (%s,CAST(%s AS json),%s,NOW())",
            (MARKER, raw, checksum),
        )
    conn.commit()

print(f'Viewer password migration applied to {len(VIEWERS)} users.')
