"""Check semantic query results against independent Python aggregations.

This is an execution regression suite, not a measurement of LLM accuracy.
"""

from collections import defaultdict
from decimal import Decimal

import duckdb

from querylens.catalog import EXAMPLES


def expected_results(database):
    with duckdb.connect(str(database), read_only=True) as db:
        orders = db.execute(
            "SELECT order_id, customer_id, order_date, channel, status, gross_amount, refund_amount FROM raw_orders"
        ).fetchall()
        customers = {
            row[0]: row[1:]
            for row in db.execute(
                "SELECT customer_id, customer_name, region FROM raw_customers"
            ).fetchall()
        }
    totals = {
        name: defaultdict(Decimal) for name in ["monthly", "channels", "regions", "customers"]
    }
    revenue = gross = refunds = Decimal(0)
    completed = cancelled = 0
    for _, customer, day, channel, status, amount, refund in orders:
        net = Decimal(str(amount)) - Decimal(str(refund)) if status == "completed" else Decimal(0)
        completed += status == "completed"
        cancelled += status == "cancelled"
        revenue += net
        if status == "completed":
            gross += Decimal(str(amount))
            refunds += Decimal(str(refund))
        for group, key in [
            ("monthly", day.replace(day=1).isoformat()),
            ("channels", channel),
            ("regions", customers[customer][1]),
            ("customers", customers[customer][0]),
        ]:
            totals[group][key] += net

    def rounded(value):
        return float(round(value, 2))

    def ordered(group):
        return [
            [key, rounded(value)]
            for key, value in sorted(totals[group].items(), key=lambda item: (-item[1], item[0]))
        ]

    return {
        "total": [[rounded(revenue)]],
        "monthly": [
            [key + "T00:00:00", rounded(value)] for key, value in sorted(totals["monthly"].items())
        ],
        "channels": ordered("channels"),
        "regions": ordered("regions"),
        "customers": ordered("customers")[:5],
        "aov": [[rounded(revenue / completed)]],
        "refunds": [[rounded(100 * refunds / gross)]],
        "completed": [[completed]],
        "cancelled": [[cancelled]],
    }


def equivalent(actual, expected):
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected, strict=True):
        if len(actual_row) != len(expected_row):
            return False
        for value, target in zip(actual_row, expected_row, strict=True):
            if isinstance(target, (float, int)):
                if not isinstance(value, (float, int)) or abs(value - target) > 0.011:
                    return False
            elif value != target:
                return False
    return True


def run(workbench):
    expected = expected_results(workbench.database)
    cases = []
    for example in EXAMPLES:
        try:
            plan = workbench.plan(example["question"], sql=example["sql"])
            result = workbench._run(plan["planned_sql"])
            passed = equivalent(result["rows"], expected[example["id"]])
            cases.append({"id": example["id"], "passed": passed})
        except Exception as error:
            cases.append({"id": example["id"], "passed": False, "error": str(error)})
    return {
        "suite": "Semantic execution regression (no LLM)",
        "passed": sum(c["passed"] for c in cases),
        "total": len(cases),
        "cases": cases,
    }
