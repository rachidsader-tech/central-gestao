import json
import os
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash


def apply(app_module):
    if os.environ.get('STAGING_MODE') != '1':
        return

    path = Path(__file__).with_name('staging_seed.json')
    if not path.exists():
        app_module.app.logger.warning('Staging seed not found.')
        return

    seed = json.loads(path.read_text(encoding='utf-8'))
    db = app_module.db
    User = app_module.User
    AppState = app_module.AppState

    with app_module.app.app_context():
        db.create_all()

        state = db.session.get(AppState, 1)
        if not state:
            state = AppState(id=1, payload=seed.get('payload') or {}, revision=1)
            db.session.add(state)
        else:
            state.payload = seed.get('payload') or {}
            state.revision = int(state.revision or 0) + 1
        state.updated_by = 'Ambiente de homologação'
        state.updated_at = datetime.utcnow()

        # Homologação usa os mesmos nomes, papéis e alocações da produção,
        # mas nunca copia senhas reais. Todos entram com senha temporária 123456.
        for data in seed.get('users') or []:
            username = (data.get('username') or '').strip().lower()
            if not username:
                continue
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(username=username)
                db.session.add(user)
            user.display_name = data.get('display_name') or username
            user.role = data.get('role') or 'viewer'
            user.project_id = data.get('project_id')
            user.active = bool(data.get('active', True))
            user.password_hash = generate_password_hash('123456')

        db.session.commit()
        app_module.app.logger.info(
            'HOMOLOGACAO READY: %s projetos, %s usuarios, snapshot %s',
            len((seed.get('payload') or {}).get('projects') or []),
            len(seed.get('users') or []),
            seed.get('capturedAt') or 'n/a',
        )
