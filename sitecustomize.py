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
