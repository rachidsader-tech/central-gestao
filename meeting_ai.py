import os
import json
import requests
from flask import request, jsonify

def _extract_response_text(payload):
    for item in payload.get("output", []) or []:
        if item.get("type") == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text" and part.get("text"):
                    return part["text"]
    return ""

def register(app_module):
    app = app_module.app

    @app.route("/api/meeting/process", methods=["POST"])
    @app_module.login_required
    def process_meeting_audio():
        app_module.require_csrf()
        user = app_module.current_user()
        project_id = (request.form.get("project_id") or "").strip()
        if not project_id or not app_module.can_edit_project(user, project_id):
            return jsonify({"error": "Sem permissão para processar esta reunião."}), 403

        audio = request.files.get("file")
        if not audio:
            return jsonify({"error": "Áudio não recebido."}), 400

        raw = audio.read()
        if not raw:
            return jsonify({"error": "Áudio vazio."}), 400
        if len(raw) > 24 * 1024 * 1024:
            return jsonify({"error": "A gravação excede 24 MB. Divida a reunião em blocos por projeto."}), 413

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return jsonify({
                "configured": False,
                "error": "Processamento automático de áudio ainda não está conectado ao serviço de transcrição."
            }), 503

        headers = {"Authorization": f"Bearer {api_key}"}
        filename = audio.filename or "reuniao.webm"
        mime = audio.mimetype or "audio/webm"

        try:
            tr = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers,
                files={"file": (filename, raw, mime)},
                data={
                    "model": os.environ.get("MEETING_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                    "language": "pt"
                },
                timeout=180,
            )
            if tr.status_code >= 400:
                app.logger.error("Falha na transcrição da reunião: %s", tr.text[:1000])
                return jsonify({"error": "Falha ao transcrever a gravação."}), 502
            transcript = (tr.json().get("text") or "").strip()
            if not transcript:
                return jsonify({"error": "A gravação foi recebida, mas não foi possível gerar transcrição."}), 422

            project = app_module.find_project(
                app_module.db.session.get(app_module.AppState, 1).payload,
                project_id
            )
            project_name = project.get("name") if project else project_id

            prompt = f"""Você é o secretário executivo de uma reunião de transformação empresarial.
Analise a transcrição abaixo do projeto {project_name}.
Não invente fatos, nomes, responsáveis, prazos ou decisões.
Retorne SOMENTE JSON válido, sem markdown, com estas chaves:
summary: resumo objetivo da discussão;
decisions: decisões efetivamente tomadas, uma por linha;
dependencies: assuntos que dependem da Diretoria, uma por linha;
commitment: principal resultado estratégico combinado até a próxima reunião.
Se uma categoria não estiver clara, use string vazia.

TRANSCRIÇÃO:
{transcript}"""

            sr = requests.post(
                "https://api.openai.com/v1/responses",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "model": os.environ.get("MEETING_SUMMARY_MODEL", "gpt-5.6-luna"),
                    "input": prompt,
                },
                timeout=120,
            )
            if sr.status_code >= 400:
                app.logger.error("Falha no resumo da reunião: %s", sr.text[:1000])
                return jsonify({
                    "configured": True,
                    "transcript": transcript,
                    "summary": "",
                    "decisions": "",
                    "dependencies": "",
                    "commitment": "",
                    "warning": "Transcrição concluída, mas o resumo automático falhou."
                })

            text = _extract_response_text(sr.json()).strip()
            structured = {}
            try:
                structured = json.loads(text)
            except Exception:
                structured = {"summary": text}

            return jsonify({
                "configured": True,
                "transcript": transcript,
                "summary": (structured.get("summary") or "").strip(),
                "decisions": (structured.get("decisions") or "").strip(),
                "dependencies": (structured.get("dependencies") or "").strip(),
                "commitment": (structured.get("commitment") or "").strip(),
            })
        except requests.RequestException:
            app.logger.exception("Erro de rede no processamento da reunião")
            return jsonify({"error": "Falha de comunicação com o serviço de transcrição."}), 502
