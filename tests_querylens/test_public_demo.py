import json
import threading
import urllib.error
import urllib.request

import pytest

from querylens.demo import COOKIE_NAME, DemoSessions
from querylens.server import make_server
from querylens.service import Workbench


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    workbench = Workbench(tmp_path_factory.mktemp("public-demo"), memory_limit="128MB", threads=1)
    server = make_server(workbench, 0, public_demo=True, allowed_hosts={"querylens.example"})
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    class Client:
        cookie = ""
        token = ""

        def request(self, path, body=None, **headers):
            request_headers = {"Host": "querylens.example", "Cookie": self.cookie, **headers}
            if body is not None:
                request_headers.update(
                    {"Content-Type": "application/json", "X-QueryLens-Token": self.token}
                )
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=request_headers,
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
                cookie = response.headers.get("Set-Cookie")
                if cookie:
                    self.cookie = cookie.split(";", 1)[0]
                return data, response.headers

        def bootstrap(self):
            data, headers = self.request("/api/bootstrap")
            self.token = data["token"]
            return data, headers

    try:
        yield Client, workbench
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_public_demo_isolates_plans_tokens_and_history(demo):
    Client, _ = demo
    first, second = Client(), Client()
    boot, headers = first.bootstrap()
    second.bootstrap()
    assert boot["mode"] == "intent" and boot["deployment"]["public_demo"]
    assert "Secure; HttpOnly; SameSite=Strict" in headers["Set-Cookie"]
    assert first.token != second.token
    plan, _ = first.request("/api/plan", {"question": "Total revenue", "backend": "intent"})
    with pytest.raises(urllib.error.HTTPError) as unauthorized:
        second.request("/api/execute", {"plan_id": plan["id"]})
    assert unauthorized.value.code == 400
    result, _ = first.request("/api/execute", {"plan_id": plan["id"]})
    assert result["rows"] == [[810152.78]]
    assert first.request("/api/history")[0][0]["question"] == "Total revenue"
    assert second.request("/api/history")[0] == []
    second.token = first.token
    with pytest.raises(urllib.error.HTTPError) as wrong_token:
        second.request("/api/execute", {"plan_id": plan["id"]})
    assert wrong_token.value.code == 403


def test_public_demo_checks_origin_host_and_unavailable_models(demo):
    Client, _ = demo
    client = Client()
    client.bootstrap()
    with pytest.raises(urllib.error.HTTPError) as origin:
        client.request("/api/plan", {"question": "Revenue"}, Origin="https://other.example")
    assert origin.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as host:
        client.request("/api/bootstrap", Host="other.example")
    assert host.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as model:
        client.request("/api/plan", {"question": "Revenue", "backend": "local"})
    assert model.value.code == 400
    assert "free demo" in json.load(model.value)["error"]
    assert client.request("/healthz", Host="health-probe")[0]["status"] == "ok"
    plan, _ = client.request(
        "/api/plan",
        {
            "question": "Web revenue",
            "sql": "SELECT SUM(net_revenue) FROM orders WHERE channel='Web'",
        },
        Origin="https://querylens.example",
    )
    result, _ = client.request("/api/execute", {"plan_id": plan["id"]})
    assert result["rows"][0][0] == pytest.approx(263750.8)


def test_demo_sessions_expire_limit_requests_and_bound_storage(demo):
    sessions = DemoSessions(ttl=3600, capacity=2)
    first, _ = sessions.get("", create=True)
    assert sessions.get(f"{COOKIE_NAME}={first.key}")[0] is first
    assert all(sessions.allow(first) for _ in range(20))
    assert not sessions.allow(first)
    for i in range(25):
        sessions.remember(first, {"id": str(i)})
    assert sessions.plan(first, "0") is None
    assert len(first.plans) == 20
    first.touched -= 3601
    assert sessions.get(f"{COOKIE_NAME}={first.key}")[0] is None
    for _ in range(3):
        sessions.get("", create=True)
    assert len(sessions.sessions) == 2
    _, workbench = demo
    workbench.prune_history(keep=1)
    with workbench._history() as db:
        assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] <= 1


def test_public_demo_requires_an_explicit_hostname(demo):
    _, workbench = demo
    with pytest.raises(ValueError, match="hostname"):
        make_server(workbench, 0, public_demo=True)
