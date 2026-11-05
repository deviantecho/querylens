"""Local HTTP interface, with an explicit bounded public-demonstration mode."""

import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from querylens.policy import QueryError
from querylens.workspaces import UploadBudget, UploadWorkspace


def make_server(workbench, port, *, public_demo=False, allowed_hosts=()):
    token = secrets.token_urlsafe(32)
    budget = UploadBudget()
    local_workspace = UploadWorkspace()
    if public_demo and not allowed_hosts:
        raise ValueError("Public demo requires an explicit allowed hostname.")
    if public_demo:
        from querylens.demo import DemoSessions

        sessions = DemoSessions()
        operations = threading.BoundedSemaphore(1)
        dashboard = workbench.dashboard()
    hosts = set(allowed_hosts)

    def bootstrap(session):
        workspace = session.workspace if public_demo else local_workspace
        with workspace.lock:
            workspace.active(workbench)
            data = workspace.dashboard or (dashboard if public_demo else workbench.dashboard())
            return {
                **data,
                "mode": "intent" if public_demo else data["mode"],
                "token": session.token if public_demo else token,
                "deployment": {"public_demo": public_demo},
                "upload_limits": {
                    "max_bytes": 2 * 1024 * 1024,
                    "max_rows": 10000,
                    "temporary": True,
                },
            }

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self):
            super().server_close()
            if public_demo:
                sessions.close()
            local_workspace.close()

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
                    return self.reply(200, bootstrap(session))
                return self.reply(200, bootstrap(None))
            if path == "/api/history":
                if public_demo:
                    session, _ = sessions.get(self.headers.get("Cookie"))
                    return self.reply(200, sessions.history(session))
                with local_workspace.lock:
                    return self.reply(200, local_workspace.active(workbench).list_history())
            if path == "/api/ai/status":
                status = workbench.ai.status()
                if public_demo:
                    status = {**status, "default_backend": "intent", "public_demo": True}
                return self.reply(200, status)
            assets = {
                "/": "index.html",
                "/app.js": "app.js",
                "/upload.js": "upload.js",
                "/style.css": "style.css",
                "/orders-template.csv": "orders-template.csv",
            }
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
            import_paths = {
                "/api/import/inspect",
                "/api/import/statuses",
                "/api/import/validate",
                "/api/import/commit",
                "/api/import/reset",
                "/api/import/cancel",
            }
            if path not in {"/api/plan", "/api/execute", *import_paths}:
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
            workspace = session.workspace if public_demo else local_workspace
            try:
                length = int(self.headers.get("Content-Length", "0"))
                maximum = (
                    2_800_000
                    if path == "/api/import/inspect"
                    else 64000
                    if path == "/api/import/validate"
                    else 24000
                )
                if not 0 < length <= maximum:
                    raise QueryError("Request is empty or too large.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise QueryError("Request must be a JSON object.")
                with workspace.lock:
                    active = workspace.active(workbench)
                    if path in import_paths:
                        if path.endswith("/inspect"):
                            result = workspace.inspect(body, budget)
                        elif path.endswith("/statuses"):
                            result = workspace.statuses(body)
                        elif path.endswith("/validate"):
                            result = workspace.validate(body)
                        elif path.endswith("/commit"):
                            workspace.commit(body, workbench)
                            if session:
                                session.plans.clear()
                                session.history.clear()
                            result = bootstrap(session)
                        elif path.endswith("/reset"):
                            workspace.reset()
                            if session:
                                session.plans.clear()
                                session.history.clear()
                            result = bootstrap(session)
                        else:
                            workspace.cancel_preview()
                            result = {"cancelled": True}
                    elif path == "/api/plan":
                        try:
                            result = self.plan(active, body)
                            workspace.remember(result)
                            if public_demo:
                                sessions.remember(session, result)
                        except QueryError as error:
                            question = body.get("question")
                            active.audit(
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
                        plan = workspace.plan(body.get("plan_id"))
                        if plan is None or (
                            public_demo and sessions.plan(session, body.get("plan_id")) is None
                        ):
                            raise QueryError(
                                "Query plan not found in this browser workspace. Draft and review a new plan."
                            )
                        result = active.execute(body.get("plan_id"))
                        if public_demo:
                            sessions.record(
                                session, plan["question"], plan["source"], "success", result=result
                            )
            except (QueryError, ValueError, UnicodeError) as error:
                status, result = 400, {"error": str(error)[:2000]}
            except Exception:
                status, result = (
                    500,
                    {
                        "error": "Unexpected application error. Try again or check the server console."
                    },
                )
                self.log_error("Application error on %s", path)
            finally:
                if public_demo:
                    try:
                        with workspace.lock:
                            if not workspace.closed:
                                workspace.active(workbench).prune_history()
                    finally:
                        operations.release()
            self.reply(status, result)

        def plan(self, active, body):
            backend = body.get("backend")
            if public_demo and body.get("sql") is None:
                if backend is not None and (
                    not isinstance(backend, str) or backend not in {"intent", "examples"}
                ):
                    raise QueryError(
                        "The free demo supports the trained classifier and examples. Run Qwen locally using the README instructions."
                    )
                backend = backend or "intent"
            return active.plan(
                body.get("question"),
                body.get("sql"),
                backend=backend,
                retrieval=body.get("retrieval", True),
            )

        def log_message(self, fmt, *args):
            # Query text and model responses are not written to console logs.
            super().log_message(fmt, *args)

    return Server(("0.0.0.0" if public_demo else "127.0.0.1", port), Handler)
