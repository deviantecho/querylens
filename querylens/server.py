"""Local HTTP interface, with an explicit bounded public-demonstration mode."""

import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from querylens.policy import QueryError


def make_server(workbench, port, *, public_demo=False, allowed_hosts=()):
    token = secrets.token_urlsafe(32)
    if public_demo and not allowed_hosts:
        raise ValueError("Public demo requires an explicit allowed hostname.")
    if public_demo:
        from querylens.demo import DemoSessions

        sessions = DemoSessions()
        operations = threading.BoundedSemaphore(1)
        dashboard = workbench.dashboard()
    hosts = set(allowed_hosts)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            if public_demo:
                self.connection.settimeout(15)

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
            if status == 429:
                self.send_header("Retry-After", "10")
            if getattr(self, "new_session", None):
                from querylens.demo import COOKIE_NAME

                self.send_header(
                    "Set-Cookie",
                    f"{COOKIE_NAME}={self.new_session.key}; Path=/; Secure; HttpOnly; SameSite=Strict",
                )
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def host_allowed(self):
            if public_demo:
                return self.headers.get("Host") in hosts
            return self.headers.get("Host") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                return self.reply(200, {"status": "ok"})
            if not self.host_allowed():
                return self.reply(403, {"error": "This hostname is not configured for QueryLens."})
            if path == "/api/bootstrap":
                if public_demo:
                    session, created = sessions.get(self.headers.get("Cookie"), create=True)
                    if created:
                        self.new_session = session
                    return self.reply(
                        200,
                        {
                            **dashboard,
                            "mode": "intent",
                            "token": session.token,
                            "deployment": {"public_demo": True},
                        },
                    )
                return self.reply(200, {**workbench.dashboard(), "token": token})
            if path == "/api/history":
                if public_demo:
                    session, _ = sessions.get(self.headers.get("Cookie"))
                    return self.reply(200, sessions.history(session))
                return self.reply(200, workbench.list_history())
            if path == "/api/ai/status":
                status = workbench.ai.status()
                if public_demo:
                    status = {**status, "default_backend": "intent", "public_demo": True}
                return self.reply(200, status)
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path in assets:
                asset = files("querylens").joinpath("static", assets[path])
                return self.reply(
                    200, asset.read_bytes(), mimetypes.guess_type(assets[path])[0] or "text/plain"
                )
            self.reply(404, {"error": "Not found."})

        def do_POST(self):
            session = None
            if public_demo:
                session, _ = sessions.get(self.headers.get("Cookie"))
            expected_token = session.token if session else token
            supplied_token = self.headers.get("X-QueryLens-Token", "")
            origin = self.headers.get("Origin")
            try:
                origin_ok = not origin or (
                    urlsplit(origin).scheme in {"https", "http"}
                    and urlsplit(origin).netloc == self.headers.get("Host")
                )
            except ValueError:
                origin_ok = False
            if (
                not self.host_allowed()
                or (public_demo and session is None)
                or not secrets.compare_digest(supplied_token.encode(), expected_token.encode())
                or not origin_ok
            ):
                return self.reply(403, {"error": "Refresh the QueryLens page and try again."})
            path = urlsplit(self.path).path
            if path not in {"/api/plan", "/api/execute"}:
                return self.reply(404, {"error": "Not found."})
            if public_demo and not sessions.allow(session):
                return self.reply(
                    429, {"error": "Demo request limit reached. Try again in a minute."}
                )
            if public_demo and not operations.acquire(blocking=False):
                return self.reply(
                    429, {"error": "The demo is running another query. Try again shortly."}
                )
            status = 200
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 24000:
                    raise QueryError("Request is empty or too large.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise QueryError("Request must be a JSON object.")
                if path == "/api/plan":
                    try:
                        backend = body.get("backend")
                        if public_demo and body.get("sql") is None:
                            if backend is not None and (
                                not isinstance(backend, str)
                                or backend not in {"intent", "examples"}
                            ):
                                raise QueryError(
                                    "The free demo supports the trained classifier and examples. Run Qwen locally using the README instructions."
                                )
                            backend = backend or "intent"
                        result = workbench.plan(
                            body.get("question"),
                            body.get("sql"),
                            backend=backend,
                            retrieval=body.get("retrieval", True),
                        )
                        if public_demo:
                            sessions.remember(session, result)
                    except QueryError as error:
                        question = body.get("question")
                        workbench.audit(
                            question[:1000] if isinstance(question, str) else "Invalid request",
                            "Planning",
                            "rejected",
                            detail=str(error),
                        )
                        if public_demo:
                            sessions.record(
                                session,
                                question if isinstance(question, str) else "Invalid request",
                                "Planning",
                                "rejected",
                                detail=str(error),
                            )
                        raise
                else:
                    plan = None
                    if public_demo:
                        plan = sessions.plan(session, body.get("plan_id"))
                        if plan is None:
                            raise QueryError(
                                "Query plan not found in this browser session. Draft and review a new plan."
                            )
                    result = workbench.execute(body.get("plan_id"))
                    if public_demo:
                        sessions.record(
                            session, plan["question"], plan["source"], "success", result=result
                        )
            except (QueryError, ValueError, UnicodeError) as error:
                status, result = 400, {"error": str(error)[:2000]}
            except Exception:
                self.reply(
                    500, {"error": "Unexpected application error. Check the server console."}
                )
                raise
            finally:
                if public_demo:
                    try:
                        workbench.prune_history()
                    finally:
                        operations.release()
            self.reply(status, result)

        def log_message(self, fmt, *args):
            # Query text and model responses are not written to console logs.
            super().log_message(fmt, *args)

    return ThreadingHTTPServer(("0.0.0.0" if public_demo else "127.0.0.1", port), Handler)
