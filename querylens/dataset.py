"""Reproducible synthetic commerce warehouse, created only when absent."""

import calendar
import random
from datetime import date

import duckdb


def create_dataset(path):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    first = ["Avery", "Riley", "Morgan", "Harper", "Jordan", "Casey", "Quinn", "Rowan"]
    last = ["Shah", "Chen", "Reed", "Patel", "Kim", "Brooks"]
    customers = [
        (
            i + 1,
            f"{first[i % 8]} {last[i // 8]}",
            ["North", "South", "East", "West"][i % 4],
            "Business" if i % 3 == 0 else "Consumer",
        )
        for i in range(48)
    ]
    orders = []
    for month in range(1, 13):
        for _ in range(120 + month * 12):
            gross = round(rng.uniform(45, 650) * (1 + month * 0.018), 2)
            cancelled = rng.random() < 0.075
            refund = (
                round(gross * rng.choice([0.25, 0.5, 1]), 2)
                if not cancelled and rng.random() < 0.12
                else 0.0
            )
            orders.append(
                (
                    len(orders) + 1,
                    rng.randint(1, 48),
                    date(2025, month, rng.randint(1, calendar.monthrange(2025, month)[1])),
                    rng.choice(["Web", "Mobile", "Partner"]),
                    "cancelled" if cancelled else "completed",
                    gross,
                    refund,
                )
            )
    write_dataset(path, customers, orders)


def write_dataset(path, customers, orders):
    """Create one warehouse atomically from already validated records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as db:
        db.execute("BEGIN")
        db.execute(
            "CREATE TABLE raw_customers (customer_id INTEGER PRIMARY KEY, customer_name VARCHAR, region VARCHAR, segment VARCHAR)"
        )
        db.execute(
            "CREATE TABLE raw_orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE, channel VARCHAR, status VARCHAR, gross_amount DOUBLE, refund_amount DOUBLE)"
        )
        db.executemany("INSERT INTO raw_customers VALUES (?, ?, ?, ?)", customers)
        db.executemany("INSERT INTO raw_orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders)
        db.execute("COMMIT")
