import base64
import io
import json
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from querylens.ai.local_llm import messages
from querylens.demo import COOKIE_NAME, DemoSessions
from querylens.errors import QueryError
from querylens.imports import MAX_ROWS, parse_spreadsheet, validate_sheet
from querylens.server import make_server
from querylens.service import Workbench
from querylens.workspaces import UploadBudget, UploadWorkspace

TEMPLATE = (Path(__file__).parents[1] / "querylens/static/orders-template.csv").read_bytes()


def payload(content=TEMPLATE, filename="orders.csv", **extra):
    if isinstance(content, str):
        content = content.encode()
    return {"filename": filename, "content": base64.b64encode(content).decode(), **extra}


def settings(sheet, **changes):
    options = {
        "shop_name": "Test shop",
        "currency": "USD",
        "date_format": "iso",
        "decimal_mark": ".",
        "one_row_per_order": True,
        "confirm_defaults": True,
        **changes,
    }
    return {"upload_id": sheet.id, "mapping": sheet.inspection()["mapping"], "options": options}


def xlsx_bytes(rows, second=None):
    book = Workbook()
    book.active.title = "Readme"
    book.active.append(["Instructions"])
    sheet = book.create_sheet("Orders")
    for row in rows:
        sheet.append(row)
    if second:
        sheet[second[0]] = second[1]
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_csv_mapping_and_independent_reconciliation():
    sheet = parse_spreadsheet(payload())
    config = settings(sheet)
    preview, normalized = validate_sheet(sheet, config)
    assert preview["valid"] and len(normalized["orders"]) == 3
    assert preview["metrics"] == {
        "net_revenue": 80,
        "completed_orders": 2,
        "average_order_value": 40,
        "refund_rate_pct": 52.94,
    }
    assert preview["dataset"]["customer_count"] == 2
    assert [c[0] for c in normalized["customers"]] == [1, 2]
    assert normalized["orders"][0][2] == date(2026, 1, 10)
    assert preview["dataset"]["start"] == "2026-01-10"
    invalid = parse_spreadsheet(
        payload(TEMPLATE.decode().replace("2026-01-10", "2026-01-10Tnot-a-time"))
    )
    assert validate_sheet(invalid, settings(invalid))[0]["valid"] is False
    minimal = parse_spreadsheet(payload("Date,Amount\n2026-01-01,25"))
    assert (
        validate_sheet(minimal, settings(minimal, status_map={"completed": "cancelled"}))[0][
            "metrics"
        ]["completed_orders"]
        == 1
    )


def test_xlsx_selects_sheet_and_preserves_numeric_cells_with_european_format():
    content = xlsx_bytes([["Date", "Amount"], [date(2024, 3, 4), 1234.56]])
    sheet = parse_spreadsheet(payload(content, "orders.xlsx", sheet="Orders"))
    assert sheet.sheets == ["Readme", "Orders"]
    preview, _ = validate_sheet(sheet, settings(sheet, currency="EUR", decimal_mark=","))
    assert preview["metrics"]["net_revenue"] == 1234.56
    assert preview["dataset"]["currency"] == "EUR"


@pytest.mark.parametrize("formula", ["=SUM(1,2)", "#DIV/0!"])
def test_xlsx_rejects_formula_and_error_cells(formula):
    content = xlsx_bytes([["Date", "Amount"], [date(2024, 3, 4), formula]])
    with pytest.raises(QueryError, match="formula|Excel error"):
        parse_spreadsheet(payload(content, "orders.xlsx", sheet="Orders"))


@pytest.mark.parametrize(
    "content,filename,message",
    [
        ("", "orders.csv", "non-empty"),
        ("Date,Date\n2026-01-01,1", "orders.csv", "unique"),
        ("\nDate,Amount\n2026-01-01,1", "orders.csv", "first row"),
        ("Date,Amount\n2026-01-01,1,2", "orders.csv", "more cells"),
        ("Date,Amount", "orders.csv", "at least one"),
        ("data", "orders.xlsm", "macro"),
        (b"\xff\xfe", "orders.csv", "UTF-8"),
        (b"not a zip", "orders.xlsx", "could not be read"),
    ],
)
def test_invalid_files_are_rejected(content, filename, message):
    with pytest.raises(QueryError, match=message):
        parse_spreadsheet(payload(content, filename))


def test_xlsx_expansion_and_row_budgets():
    data = io.BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", b"x" * (17 * 1024 * 1024))
    with pytest.raises(QueryError, match="expands"):
        parse_spreadsheet(payload(data.getvalue(), "large.xlsx"))
    with pytest.raises(QueryError, match="10,000"):
        parse_spreadsheet(payload("Date,Amount\n" + "2026-01-01,1\n" * (MAX_ROWS + 1)))


@pytest.mark.parametrize(
    "replacement,message",
    [
        (("SHOP-002", "SHOP-001"), "unique"),
        (("2026-01-10", "2026-02-31"), "day"),
        (("100.00,20.00", "100.00,120.00"), "larger"),
        (("100.00,20.00", "-100.00,0.00"), "non-negative"),
        (("paid", "pending"), "status"),
        (("Riley Chen", ""), "blank"),
        (("Avery Shah,North,Store", "Avery Shah,South,Store"), "conflicting"),
        (("North,Web,USD", "North,Web,EUR"), "Mixed currencies"),
    ],
)
def test_row_errors_block_the_whole_import(replacement, message):
    content = TEMPLATE.decode().replace(*replacement)
    sheet = parse_spreadsheet(payload(content))
    preview, normalized = validate_sheet(sheet, settings(sheet))
    assert preview["valid"] is False and normalized is None
    assert any(message in issue["message"] for issue in preview["errors"])
    assert all(issue["row"] >= 2 for issue in preview["errors"])


def test_explicit_dates_statuses_currency_and_missing_fields():
    sheet = parse_spreadsheet(payload('Date;Amount;Status\n04/03/2024;"1.234,56";settled\n'))
    config = settings(
        sheet,
        currency="EUR",
        decimal_mark=",",
        date_format="dmy",
        status_map={"settled": "completed"},
    )
    preview, _ = validate_sheet(sheet, config)
    assert preview["metrics"]["net_revenue"] == 1234.56
    assert preview["dataset"]["start"] == "2024-03-04"
    assert {"region", "channel", "customer_name"}.issubset(preview["dataset"]["unavailable_fields"])
    assert preview["dataset"]["customer_count"] is None
    assert any("refund" in w.lower() for w in preview["dataset"]["warnings"])
    config["options"]["confirm_defaults"] = False
    with pytest.raises(QueryError, match="assumptions"):
        validate_sheet(sheet, config)


@pytest.mark.parametrize("field", ["currency", "decimal_mark", "date_format"])
def test_malformed_options_are_user_errors(field):
    sheet = parse_spreadsheet(payload())
    with pytest.raises(QueryError):
        validate_sheet(sheet, settings(sheet, **{field: []}))


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return Workbench(tmp_path_factory.mktemp("import-sample"), memory_limit="128MB", threads=1)


def test_upload_workspace_blocks_stale_plans_and_missing_dimensions_and_cleans_up(sample):
    workspace, budget = UploadWorkspace(), UploadBudget(capacity=1)
    try:
        inspection = workspace.inspect(payload("Date,Amount\n2024-01-01,25"), budget)
        config = settings(workspace.pending, currency="INR")
        preview = workspace.validate(config)
        dashboard = workspace.commit(
            {"upload_id": inspection["upload_id"], "preview_id": preview["preview_id"]}, sample
        )
        directory = Path(workspace.directory.name)
        assert dashboard["metrics"]["net_revenue"] == 25
        assert dashboard["dataset"]["currency"] == "INR"
        assert "2024-01-01" in dashboard["period"]
        assert "USD" not in " ".join(r["text"] for r in dashboard["rules"])
        active = workspace.active(sample)
        with pytest.raises(QueryError, match="does not provide"):
            active.plan(
                "Regional revenue",
                "SELECT region, SUM(net_revenue) FROM orders JOIN customers USING (customer_id) GROUP BY region",
            )
        plan = active.plan("Revenue", "SELECT SUM(net_revenue) FROM orders")
        workspace.remember(plan)
        assert active.execute(plan["id"])["rows"] == [[25]]
        workspace.reset()
        assert not directory.exists() and workspace.plan(plan["id"]) is None
        assert workspace.active(sample) is sample
        assert budget.slots.acquire(blocking=False)
    finally:
        workspace.close()


def test_import_failure_keeps_current_shop_and_expired_preview_cannot_commit(sample):
    workspace, budget = UploadWorkspace(), UploadBudget(capacity=1)
    try:
        first = workspace.inspect(payload(), budget)
        preview = workspace.validate(settings(workspace.pending))
        workspace.commit(
            {"upload_id": first["upload_id"], "preview_id": preview["preview_id"]}, sample
        )
        active = workspace.workbench
        with pytest.raises(QueryError):
            workspace.inspect(payload("bad", "bad.xlsx"), budget)
        assert workspace.workbench is active
        other = workspace.inspect(payload(), budget)
        preview = workspace.validate(settings(workspace.pending))
        workspace.inspected_at -= 901
        with pytest.raises(QueryError, match="expired"):
            workspace.commit(
                {"upload_id": other["upload_id"], "preview_id": preview["preview_id"]}, sample
            )
        assert workspace.workbench is active
    finally:
        workspace.close()


def test_public_session_expiry_removes_upload_and_releases_capacity(sample):
    sessions, budget = DemoSessions(capacity=1), UploadBudget(capacity=1)
    session, _ = sessions.get("", create=True)
    session.workspace.inspect(payload(), budget)
    with pytest.raises(QueryError, match="eight"):
        UploadWorkspace().inspect(payload(), budget)
    session.touched -= 3601
    assert sessions.get(f"{COOKIE_NAME}={session.key}")[0] is None
    assert session.workspace.closed and session.workspace.pending is None
    assert budget.slots.acquire(blocking=False)


def test_llm_context_uses_uploaded_period_and_currency():
    context = messages(
        "Revenue?",
        [],
        False,
        dataset={
            "start": "2024-03-01",
            "end": "2024-04-01",
            "currency": "INR",
            "unavailable_fields": ["channel"],
        },
    )[0]["content"]
    assert "INR" in context and "2024-03-01" in context
    assert "amounts are USD" not in context and "All data covers 2025" not in context
    assert "channel" in context


@pytest.mark.parametrize("public", [False, True])
def test_http_upload_review_switch_reset_and_session_isolation(sample, public):
    server = make_server(
        sample, 0, public_demo=public, allowed_hosts={"querylens.example"} if public else ()
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    class Client:
        token, cookie = "", ""

        def request(self, path, body=None):
            headers = {
                "Content-Type": "application/json",
                "X-QueryLens-Token": self.token,
                "Cookie": self.cookie,
            }
            if public:
                headers["Host"] = "querylens.example"
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}{path}",
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.headers.get("Set-Cookie"):
                    self.cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                result = json.load(response)
                if "token" in result:
                    self.token = result["token"]
                return result

    try:
        first, second = Client(), Client()
        first.request("/api/bootstrap")
        if public:
            second.request("/api/bootstrap")
        stale = first.request("/api/plan", {"question": "Total revenue", "backend": "examples"})
        inspection = first.request("/api/import/inspect", payload())
        config = {
            "upload_id": inspection["upload_id"],
            "mapping": inspection["mapping"],
            "options": {
                "shop_name": "Private shop",
                "currency": "USD",
                "one_row_per_order": True,
                "confirm_defaults": True,
            },
        }
        if public:
            with pytest.raises(urllib.error.HTTPError) as foreign_preview:
                second.request("/api/import/validate", config)
            assert foreign_preview.value.code == 400
        preview = first.request("/api/import/validate", config)
        imported = first.request(
            "/api/import/commit",
            {"upload_id": inspection["upload_id"], "preview_id": preview["preview_id"]},
        )
        assert imported["dataset"]["shop_name"] == "Private shop"
        assert imported["metrics"]["net_revenue"] == 80
        assert first.request("/api/bootstrap")["dataset"]["kind"] == "upload"
        with pytest.raises(urllib.error.HTTPError) as old_plan:
            first.request("/api/execute", {"plan_id": stale["id"]})
        assert old_plan.value.code == 400
        plan = first.request("/api/plan", {"question": "Total revenue", "backend": "examples"})
        assert first.request("/api/execute", {"plan_id": plan["id"]})["rows"] == [[80]]
        if public:
            untouched = second.request("/api/bootstrap")
            assert (
                untouched["dataset"]["kind"] == "sample"
                and untouched["metrics"]["net_revenue"] == 810152.78
            )
            assert second.request("/api/history") == []
            with pytest.raises(urllib.error.HTTPError):
                second.request("/api/execute", {"plan_id": plan["id"]})
        reset = first.request("/api/import/reset", {})
        assert reset["dataset"]["kind"] == "sample" and reset["metrics"]["net_revenue"] == 810152.78
        with pytest.raises(urllib.error.HTTPError):
            first.request("/api/execute", {"plan_id": plan["id"]})
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
