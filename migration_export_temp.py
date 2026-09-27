import os, hmac
from flask import request, abort, Response, jsonify
from sqlalchemy import text

_ALLOWED = {
    "kaz_attachments",
    "kaz_meeting_attachments",
    "kaz_meeting_audio_segments",
    "kaz_project_attachments",
}

_ENV_KEYS = [
    "OPENAI_API_KEY",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "DAILY_IMPORT_TOKEN",
    "KAZ_VIEWER_TEMP_PASSWORD",
    "MEETING_TRANSCRIBE_MODEL",
    "MEETING_SUMMARY_MODEL",
    "SECRET_KEY",
]

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

    @app.route("/__migration-export/env")
    def migration_export_env():
        if not _authorized():
            abort(404)
        return jsonify({key: os.environ.get(key) for key in _ENV_KEYS if os.environ.get(key) is not None})

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
