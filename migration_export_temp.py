import os, hmac
from flask import request, abort, Response, jsonify
from sqlalchemy import text

_ALLOWED = {
    "kaz_attachments",
    "kaz_meeting_attachments",
    "kaz_meeting_audio_segments",
    "kaz_project_attachments",
}

def register(app_module):
    app = app_module.app
    db = app_module.db

    def _authorized():
        expected = os.environ.get("MIGRATION_EXPORT_TOKEN") or ""
        supplied = request.headers.get("X-Migration-Token") or request.args.get("token") or ""
        return bool(expected) and hmac.compare_digest(expected, supplied)

    @app.route("/__migration-export/health")
    def migration_export_health():
        if not _authorized():
            abort(404)
        return jsonify({"ok": True})

    @app.route("/__migration-export/<table>/<int:row_id>")
    def migration_export_binary(table, row_id):
        if not _authorized() or table not in _ALLOWED:
            abort(404)
        row = db.session.execute(
            text(f'SELECT file_data, mime_type FROM "{table}" WHERE id=:id'),
            {"id": row_id},
        ).mappings().first()
        if not row:
            abort(404)
        raw = row["file_data"] or b""
        return Response(
            raw,
            mimetype=row["mime_type"] or "application/octet-stream",
            headers={"Content-Length": str(len(raw)), "Cache-Control": "no-store"},
        )
