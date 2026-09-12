# Ensures nested JSON mutations on AppState.payload are persisted by SQLAlchemy.
try:
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import flag_modified
    _original_commit = Session.commit

    def _kaz_commit(self):
        for obj in list(self.identity_map.values()):
            if obj.__class__.__name__ == 'AppState' and hasattr(obj, 'payload'):
                try:
                    flag_modified(obj, 'payload')
                except Exception:
                    pass
        return _original_commit(self)

    Session.commit = _kaz_commit
except Exception:
    pass

# One-time first-access credential migration for the eight read-only users.
# The actual temporary password comes from a Render environment variable and is
# never committed to the repository. A database marker prevents re-applying it
# after a user changes their password.
try:
    import os, json, hashlib
    import psycopg
    from werkzeug.security import generate_password_hash

    _db_url = os.environ.get('DATABASE_URL')
    _temp_password = os.environ.get('KAZ_VIEWER_TEMP_PASSWORD')
    _marker = 'viewer-temp-password-v1'
    _viewer_users = ['julia','michele','kawe','cole','lucas','julio','felipe','lais']

    if _db_url and _temp_password:
        with psycopg.connect(_db_url) as _conn:
            with _conn.cursor() as _cur:
                _cur.execute("SELECT to_regclass('public.central_migration_backups')")
                _backup_table = _cur.fetchone()[0]
                if _backup_table:
                    _cur.execute("SELECT 1 FROM central_migration_backups WHERE backup_key=%s", (_marker,))
                    if _cur.fetchone() is None:
                        _password_hash = generate_password_hash(_temp_password)
                        _cur.execute(
                            "UPDATE kaz_users SET password_hash=%s WHERE role='viewer' AND username = ANY(%s)",
                            (_password_hash, _viewer_users),
                        )
                        _payload = {
                            'action': 'temporary_password_set',
                            'users': _viewer_users,
                            'count': _cur.rowcount,
                        }
                        _raw = json.dumps(_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                        _checksum = hashlib.sha256(_raw.encode('utf-8')).hexdigest()
                        _cur.execute(
                            "INSERT INTO central_migration_backups (backup_key, payload, checksum, created_at) VALUES (%s, CAST(%s AS json), %s, NOW())",
                            (_marker, _raw, _checksum),
                        )
            _conn.commit()
except Exception:
    # This operational migration must never prevent the application from booting.
    pass
