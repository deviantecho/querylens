"""Loopback-only HTTP interface for a single-user local portfolio demo."""

import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from querylens.policy import QueryError


def make_server(workbench, port):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, kind="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, allow_nan=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def host_allowed(self):
            return self.headers.get("Host") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def do_GET(self):
            if not self.host_allowed():
                return self.reply(403, {"error": "Use the loopback URL printed by QueryLens."})
            path = urlsplit(self.path).path
            if path == "/api/bootstrap":
                return self.reply(200, {**workbench.dashboard(), "token": token})
            if path == "/api/history":
                return self.reply(200, workbench.list_history())
            if path == "/api/ai/status":
                return self.reply(200, workbench.ai.status())
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path in assets:
                asset = files("querylens").joinpath("static", assets[path])
                return self.reply(
                    200, asset.read_bytes(), mimetypes.guess_type(assets[path])[0] or "text/plain"
                )
            self.reply(404, {"error": "Not found."})

        def do_POST(self):
            if not self.host_allowed() or self.headers.get("X-QueryLens-Token") != token:
                return self.reply(403, {"error": "Refresh the QueryLens page and try again."})
            path = urlsplit(self.path).path
            if path not in {"/api/plan", "/api/execute"}:
                return self.reply(404, {"error": "Not found."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 24000:
                    raise QueryError("Request is empty or too large.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise QueryError("Request must be a JSON object.")
                if path == "/api/plan":
                    try:
                        result = workbench.plan(
                            body.get("question"),
                            body.get("sql"),
                            backend=body.get("backend"),
                            retrieval=body.get("retrieval", True),
                        )
                    except QueryError as error:
                        question = body.get("question")
                        workbench.audit(
                            question[:1000] if isinstance(question, str) else "Invalid request",
                            "Planning",
                            "rejected",
                            detail=str(error),
                        )
                        raise
                else:
                    result = workbench.execute(body.get("plan_id"))
                self.reply(200, result)
            except (QueryError, ValueError, UnicodeError) as error:
                self.reply(400, {"error": str(error)[:2000]})
            except Exception:
                self.reply(
                    500, {"error": "Unexpected application error. Check the server console."}
                )
                raise

        def log_message(self, fmt, *args):
            # Query text and model responses are not written to console logs.
            super().log_message(fmt, *args)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
