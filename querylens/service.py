"""Generate -> validate -> plan -> human review -> execute -> audit."""

import json
import math
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timezone

import duckdb

from querylens.ai.engine import AIEngine
from querylens.catalog import EXAMPLES, RULES, SCHEMA
from querylens.dataset import create_dataset
from querylens.planner import QueryPlanner
from querylens.policy import QueryError


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def native(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class Workbench:
    def __init__(self, data_dir, *, memory_limit="256MB", threads=2):
        self.data_dir = data_dir
        self.database = data_dir / "commerce.duckdb"
        self.history = data_dir / "history.sqlite3"
        create_dataset(self.database)
        self.lock = threading.RLock()
        self.database_config = {
            "enable_external_access": "false",
            "threads": str(threads),
            "memory_limit": memory_limit,
        }
        with self._history() as db:
            db.execute("CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, created TEXT, question TEXT, source TEXT, status TEXT, duration_ms REAL, row_count INTEGER, detail TEXT)"
            )
        self.planner = QueryPlanner()
        self.ai = AIEngine(data_dir)

    def _history(self):
        return sqlite3.connect(self.history, timeout=10)

    def _run(self, planned, limit=200):
        # Bound expensive queries as well as the number of returned rows. External
        # access is disabled independently of AST checks and read-only file mode.
        with (
            self.lock,
            duckdb.connect(
                str(self.database),
                read_only=True,
                config=self.database_config,
            ) as db,
        ):
            timer = threading.Timer(5, db.interrupt)
            timer.start()
            try:
                cursor = db.execute(
                    "SELECT * FROM (\n"
                    + planned.rstrip(";\n ")
                    + f"\n) AS result LIMIT {limit + 1}"
                )
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            finally:
                timer.cancel()
                timer.join()
        return {
            "columns": columns,
            "rows": [[native(v) for v in row] for row in rows[:limit]],
            "row_count": min(len(rows), limit),
            "truncated": len(rows) > limit,
        }

    def _compile(self, sql):
        try:
            with self.lock:
                compiled = self.planner.compile(sql)
                with duckdb.connect(
                    str(self.database),
                    read_only=True,
                    config=self.database_config,
                ) as db:
                    db.execute("EXPLAIN " + compiled.executable_sql)
            return compiled
        except QueryError:
            raise
        except Exception as error:
            raise QueryError("Query planning failed: " + str(error)[:1500]) from error

    def plan(self, question, sql=None, backend=None, retrieval=True, repair=True):
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            raise QueryError("Enter a question of 1 to 1,000 characters.")
        context = self.ai.retriever.search(question)
        trace = {"backend": "manual", "attempts": []}
        if sql is None:
            answer = self.ai.draft(question, backend, retrieval)
            sql, source, explanation = answer["sql"], answer["source"], answer["explanation"]
            context = answer["context"]
            trace = {**answer["trace"], "attempts": []}
        else:
            source, explanation = (
                "SQL editor",
                "User-written SQL, validated and expanded through QueryLens business models.",
            )
        try:
            compiled = self._compile(sql)
            trace["attempts"].append({"sql": sql, "valid": True})
        except QueryError as error:
            trace["attempts"].append({"sql": sql, "valid": False, "error": str(error)})
            if not repair or trace["backend"] != "local":
                raise
            answer = self.ai.draft(
                question, "local", retrieval, repair={"sql": sql, "error": str(error)}
            )
            sql, source, explanation = answer["sql"], answer["source"], answer["explanation"]
            compiled = self._compile(sql)
            trace = {
                **answer["trace"],
                "attempts": trace["attempts"] + [{"sql": sql, "valid": True}],
            }
        plan = {
            "id": uuid.uuid4().hex,
            "question": question.strip(),
            "sql": compiled.query_sql,
            "planned_sql": compiled.executable_sql,
            "source": source,
            "explanation": explanation,
            "tables": list(compiled.models),
            "calculated_fields": list(compiled.calculated_fields),
            "model_version": compiled.model_version,
            "context": context,
            "ai_trace": trace,
            "created": timestamp(),
        }
        with self._history() as db:
            db.execute("INSERT INTO plans VALUES (?, ?)", (plan["id"], json.dumps(plan)))
        return plan

    def execute(self, plan_id):
        if not isinstance(plan_id, str):
            raise QueryError("Choose a reviewed query plan first.")
        with self._history() as db:
            record = db.execute("SELECT body FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not record:
            raise QueryError("Query plan not found. Generate and review a plan first.")
        plan = json.loads(record[0])
        started = time.perf_counter()
        try:
            result = self._run(plan["planned_sql"])
        except Exception as error:
            self.audit(
                plan["question"],
                plan["source"],
                "error",
                (time.perf_counter() - started) * 1000,
                0,
                str(error)[:1000],
            )
            raise QueryError("Query execution failed: " + str(error)[:1000]) from error
        duration = round((time.perf_counter() - started) * 1000, 2)
        self.audit(plan["question"], plan["source"], "success", duration, result["row_count"], "")
        return {
            **result,
            "duration_ms": duration,
            "source": plan["source"],
            "question": plan["question"],
            "sql": plan["sql"],
        }

    def audit(self, question, source, status, duration=0, rows=0, detail=""):
        with self._history() as db:
            db.execute(
                "INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, timestamp(), question, source, status, duration, rows, detail),
            )

    def list_history(self):
        with self._history() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute("SELECT * FROM audit ORDER BY created DESC LIMIT 50")
            ]

    def prune_history(self, keep=2048):
        """Bound ephemeral public-demo storage; local history is retained by default."""
        with self._history() as db:
            for table in ("plans", "audit"):
                db.execute(
                    f"DELETE FROM {table} WHERE rowid NOT IN "
                    f"(SELECT rowid FROM {table} ORDER BY rowid DESC LIMIT ?)",
                    (keep,),
                )

    def dashboard(self):
        # These are application-owned fixed queries against the semantic model.
        trend = self._run(self.planner.compile(EXAMPLES[1]["sql"]).executable_sql)
        channels = self._run(self.planner.compile(EXAMPLES[2]["sql"]).executable_sql)
        total = self._run(self.planner.compile(EXAMPLES[0]["sql"]).executable_sql)["rows"][0][0]
        count = self._run(self.planner.compile(EXAMPLES[7]["sql"]).executable_sql)["rows"][0][0]
        aov = self._run(self.planner.compile(EXAMPLES[5]["sql"]).executable_sql)["rows"][0][0]
        refunds = self._run(self.planner.compile(EXAMPLES[6]["sql"]).executable_sql)["rows"][0][0]
        return {
            "name": "QueryLens",
            "mode": self.ai.default_backend,
            "ai": {
                "default_backend": self.ai.default_backend,
                "local_model_ready": self.ai.status()["local_model_ready"],
                "intent_accuracy": self.ai.report["evaluation"]["accuracy"],
            },
            "metrics": {
                "net_revenue": total,
                "completed_orders": count,
                "average_order_value": aov,
                "refund_rate_pct": refunds,
            },
            "trend": trend,
            "channels": channels,
            "examples": [{"question": e["question"]} for e in EXAMPLES],
            "schema": SCHEMA,
            "rules": RULES,
            "period": "Jan - Dec 2025",
            "dataset": "Synthetic commerce data / seed 42",
        }
