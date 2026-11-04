import json
import threading
import urllib.error
import urllib.request

import duckdb
import pytest

from querylens import provider
from querylens.catalog import EXAMPLES, retrieve
from querylens.evaluation import run
from querylens.policy import QueryError, validate
from querylens.server import make_server
from querylens.service import Workbench


@pytest.fixture(autouse=True)
def fixed_example_mode(monkeypatch):
    monkeypatch.setenv("QUERYLENS_MODE", "examples")


@pytest.fixture(scope="module")
def workbench(tmp_path_factory):
    threading.stack_size(8 * 1024 * 1024)
    return Workbench(tmp_path_factory.mktemp("querylens"))


def test_semantic_execution_matches_independent_python_aggregations(workbench):
    result = run(workbench)
    assert result["passed"] == result["total"] == 9, result


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT * FROM orders; DROP TABLE orders",
        "SELECT * FROM raw_orders",
        "SELECT * FROM main.raw_orders",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM read_csv('private.csv')",
        "SELECT read_blob('private.txt') FROM orders",
        "SELECT * FROM range(1000000000000)",
        "COPY (SELECT * FROM orders) TO 'out.csv'",
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        "SELECT * INTO backup FROM orders",
        "WITH RECURSIVE x AS (SELECT * FROM orders UNION ALL SELECT * FROM x) SELECT * FROM x",
        "SELECT repeat('x', 1000000000) FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT 1",
    ],
)
def test_policy_rejects_writes_external_sources_and_unmodeled_data(sql):
    with pytest.raises(QueryError):
        validate(sql)


def test_cte_queries_and_literal_semicolons_are_supported(workbench):
    plan = workbench.plan(
        "Manual analysis",
        "WITH selected AS (SELECT customer_id, net_revenue FROM orders) SELECT ';' AS label, ROUND(SUM(net_revenue), 2) AS revenue FROM selected",
    )
    result = workbench.execute(plan["id"])
    assert result["rows"] == [[";", 810152.78]]


def test_result_limit_is_enforced_and_audited(workbench):
    plan = workbench.plan("All orders", "SELECT order_id FROM orders ORDER BY order_id")
    result = workbench.execute(plan["id"])
    assert result["row_count"] == 200
    assert result["truncated"] is True
    assert len(result["rows"]) == 200
    record = next(r for r in workbench.list_history() if r["question"] == "All orders")
    assert record["status"] == "success" and record["row_count"] == 200


def test_review_plan_is_required(workbench):
    with pytest.raises(QueryError, match="not found"):
        workbench.execute("invented-plan")


def test_unknown_columns_fail_during_plan(workbench):
    with pytest.raises(QueryError, match="planning failed"):
        workbench.plan("Unknown column", "SELECT missing_column FROM orders")


def test_demo_never_claims_arbitrary_language_generation(monkeypatch):
    monkeypatch.delenv("QUERYLENS_MODEL", raising=False)
    for example in EXAMPLES:
        sql, source, _ = provider.generate(example["question"], [])
        assert sql == example["sql"] and source == "Bundled example"
    with pytest.raises(QueryError, match="Example mode"):
        provider.generate("Predict revenue for 2030", [])


def test_context_retrieval_surfaces_customer_region_rule():
    assert "customers" in [r["id"] for r in retrieve("Compare revenue across customer regions")]


def test_database_is_read_only_and_external_access_is_disabled(workbench):
    with duckdb.connect(
        str(workbench.database), read_only=True, config={"enable_external_access": "false"}
    ) as db:
        with pytest.raises(duckdb.Error):
            db.execute("DELETE FROM raw_orders")
        with pytest.raises(duckdb.Error):
            db.execute("SELECT * FROM read_csv('nonexistent.csv')")


def test_ollama_request_and_invalid_output(monkeypatch):
    monkeypatch.setenv("QUERYLENS_MODEL", "test-model")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "sql": "SELECT SUM(net_revenue) FROM orders",
                                "explanation": "Uses net revenue.",
                            }
                        )
                    }
                }
            ).encode()

    def respond(request, timeout):
        payload = json.loads(request.data)
        assert request.full_url == "http://127.0.0.1:11434/api/chat"
        assert payload["model"] == "test-model"
        assert payload["format"]["required"] == ["sql", "explanation"]
        assert timeout == 90
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    assert provider.generate("Revenue?", [])[1] == "Ollama / test-model"
    monkeypatch.setattr(Response, "read", lambda *_: b"{}")
    with pytest.raises(QueryError, match="invalid structured output"):
        provider.generate("Revenue?", [])


def test_http_plan_review_execute_and_cross_site_protection(workbench, monkeypatch):
    monkeypatch.delenv("QUERYLENS_MODEL", raising=False)
    server = make_server(workbench, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-QueryLens-Token"] = token
        req = urllib.request.Request(
            url + path, data=json.dumps(body).encode() if body else None, headers=headers
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    try:
        boot = request("/api/bootstrap")
        assert boot["mode"] == "examples"
        ai = request("/api/ai/status")
        assert ai["intent_model"]["test_count"] == 36
        assert ai["retrieval"]["includes_test_questions"] is False
        with pytest.raises(urllib.error.HTTPError) as invalid_backend:
            request("/api/plan", {"question": "total revenue", "backend": []}, boot["token"])
        assert invalid_backend.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as rejected:
            request("/api/plan", {"question": "total revenue"})
        assert rejected.value.code == 403
        plan = request("/api/plan", {"question": "total revenue"}, boot["token"])
        result = request("/api/execute", {"plan_id": plan["id"]}, boot["token"])
        assert result["rows"] == [[810152.78]]
        with pytest.raises(urllib.error.HTTPError) as invalid:
            request("/api/plan", {"question": "Unsafe", "sql": "DROP TABLE orders"}, boot["token"])
        assert invalid.value.code == 400
        assert any(
            r["status"] == "rejected" and r["question"] == "Unsafe" for r in request("/api/history")
        )
        with urllib.request.urlopen(url + "/") as page:
            assert b"QueryLens" in page.read()
            assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
