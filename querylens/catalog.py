"""Business definitions and an explicit, finite offline example library."""

import re

from querylens.modeling import get_registry

RULES = [
    {
        "id": "net-revenue",
        "title": "Net revenue",
        "text": "Net revenue is gross_amount minus refund_amount for completed orders only. Cancelled orders contribute zero. All money is USD.",
    },
    {
        "id": "average-order",
        "title": "Average order value",
        "text": "Average order value is net revenue divided by the number of completed orders. Exclude cancelled orders from the denominator.",
    },
    {
        "id": "refund-rate",
        "title": "Refund rate",
        "text": "Refund rate is the refunded dollar amount divided by gross revenue for completed orders, multiplied by 100. It is not a count of refunded orders.",
    },
    {
        "id": "customers",
        "title": "Customers and regions",
        "text": "Join orders.customer_id to customers.customer_id. Regions are North, South, East and West. A customer can place many orders.",
    },
    {
        "id": "time",
        "title": "Reporting window",
        "text": "Synthetic demo data covers January through December 2025. order_date is the order date. Group monthly trends using DATE_TRUNC('month', order_date).",
    },
    {
        "id": "channels",
        "title": "Sales channels",
        "text": "channel is Web, Mobile or Partner. status is completed or cancelled. Synthetic data is generated with seed 42 and contains no real customer data.",
    },
]

EXAMPLES = [
    {
        "id": "total",
        "question": "What is our total net revenue?",
        "aliases": ["total revenue", "show total revenue"],
        "sql": "SELECT ROUND(SUM(net_revenue), 2) AS net_revenue FROM orders",
    },
    {
        "id": "monthly",
        "question": "Show monthly net revenue",
        "aliases": ["monthly revenue", "revenue trend"],
        "sql": "SELECT DATE_TRUNC('month', order_date) AS month, ROUND(SUM(net_revenue), 2) AS net_revenue FROM orders GROUP BY 1 ORDER BY 1",
    },
    {
        "id": "channels",
        "question": "Which sales channels generate the most revenue?",
        "aliases": ["revenue by channel", "sales by channel"],
        "sql": "SELECT channel, ROUND(SUM(net_revenue), 2) AS net_revenue FROM orders GROUP BY channel ORDER BY net_revenue DESC, channel",
    },
    {
        "id": "regions",
        "question": "Compare revenue across regions",
        "aliases": ["revenue by region"],
        "sql": "SELECT c.region, ROUND(SUM(o.net_revenue), 2) AS net_revenue FROM orders o JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.region ORDER BY net_revenue DESC, c.region",
    },
    {
        "id": "customers",
        "question": "Who are our top 5 customers?",
        "aliases": ["top customers", "top 5 customers by revenue"],
        "sql": "SELECT c.customer_name, ROUND(SUM(o.net_revenue), 2) AS net_revenue FROM orders o JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.customer_id, c.customer_name ORDER BY net_revenue DESC, c.customer_name LIMIT 5",
    },
    {
        "id": "aov",
        "question": "What is our average order value?",
        "aliases": ["average order value", "aov"],
        "sql": "SELECT ROUND(SUM(net_revenue) / NULLIF(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0), 2) AS average_order_value FROM orders",
    },
    {
        "id": "refunds",
        "question": "What percentage of revenue was refunded?",
        "aliases": ["refund rate", "refund percentage"],
        "sql": "SELECT ROUND(100.0 * SUM(refund_amount) / NULLIF(SUM(gross_amount), 0), 2) AS refund_rate_pct FROM orders WHERE status = 'completed'",
    },
    {
        "id": "completed",
        "question": "How many orders were completed?",
        "aliases": ["completed orders"],
        "sql": "SELECT COUNT(*) AS completed_orders FROM orders WHERE status = 'completed'",
    },
    {
        "id": "cancelled",
        "question": "How many orders were cancelled?",
        "aliases": ["cancelled orders"],
        "sql": "SELECT COUNT(*) AS cancelled_orders FROM orders WHERE status = 'cancelled'",
    },
]


def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def retrieve(question, limit=3):
    """Rank short business rules by token overlap; always include revenue semantics."""
    tokens = set(normalize(question).split())
    ranked = sorted(
        RULES, key=lambda r: -len(tokens & set(normalize(r["title"] + " " + r["text"]).split()))
    )
    selected = [RULES[0]] + [rule for rule in ranked if rule["id"] != RULES[0]["id"]]
    return selected[:limit]


def example_for(question):
    key = normalize(question)
    return next(
        (
            e
            for e in EXAMPLES
            if key in {normalize(e["question"]), *(normalize(a) for a in e["aliases"])}
        ),
        None,
    )


SCHEMA = get_registry().public_schema()
