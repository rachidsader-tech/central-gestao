import gzip, os
_path = os.path.join(os.path.dirname(__file__), 'app_core.py.gz')
with gzip.open(_path, 'rt', encoding='utf-8') as _f:
    _source = _f.read()
exec(compile(_source, _path, 'exec'), globals(), globals())
