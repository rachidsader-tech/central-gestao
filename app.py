import gzip, os
from flask import render_template

_path = os.path.join(os.path.dirname(__file__), 'app_core.py.gz')
with gzip.open(_path, 'rt', encoding='utf-8') as _f:
    _source = _f.read()
exec(compile(_source, _path, 'exec'), globals(), globals())

# Hotfix: o template principal é renderizado pelo arquivo HTML normal.
# Isso evita depender de templates/index.html.gz, que apresentou corrupção de CRC.
@login_required
def _fixed_index():
    s = db.session.get(AppState, 1)
    return render_template(
        'index.html',
        initial_state=s.payload,
        revision=s.revision,
        user=public_user(current_user()),
        csrf=session['csrf'],
        project_statuses=PROJECT_STATUSES,
        dependency_statuses=DEPENDENCY_STATUSES,
        directors=DIRECTOR_NAMES,
    )

app.view_functions['index'] = _fixed_index
