from copy import deepcopy
from importlib.metadata import requires

import duckdb
import pytest

from querylens.errors import QueryError
from querylens.modeling import ModelRegistry, get_registry
from querylens.planner import QueryPlanner


def config():
    return {
        "version": 1,
        "models": {
            "sales": {
                "source": "facts",
                "primary_key": "id",
                "columns": {
                    "id": {"type": "INTEGER"},
                    "after_fee": {"type": "DOUBLE", "expression": "net - 2"},
                    "net": {"type": "DOUBLE", "expression": "gross - refund"},
                    "gross": {"type": "DOUBLE"},
                    "refund": {"type": "DOUBLE"},
                },
            }
        },
    }


def execute(sql, registry=None):
    planner = QueryPlanner(registry)
    with duckdb.connect() as db:
        db.execute("CREATE TABLE facts (id INTEGER, gross DOUBLE, refund DOUBLE)")
        db.execute("INSERT INTO facts VALUES (1, 20, 5), (2, 30, 0)")
        db.execute(
            "CREATE TABLE raw_orders (order_id INTEGER, customer_id INTEGER, order_date DATE, channel VARCHAR, status VARCHAR, gross_amount DOUBLE, refund_amount DOUBLE)"
        )
        db.execute(
            "INSERT INTO raw_orders VALUES (1, 5, '2025-01-01', 'Web', 'completed', 20, 5), (2, 6, '2025-01-02', 'Mobile', 'cancelled', 30, 0)"
        )
        db.execute(
            "CREATE TABLE raw_customers (customer_id INTEGER, customer_name VARCHAR, region VARCHAR, segment VARCHAR)"
        )
        db.execute(
            "INSERT INTO raw_customers VALUES (5, 'Riley Shah', 'West', 'Consumer'), (6, 'Quinn Kim', 'East', 'Consumer')"
        )
        plan = planner.compile(sql)
        return db.execute(plan.executable_sql).fetchall(), plan


def test_package_uses_independent_database_parser_and_ml_dependencies():
    dependencies = requires("querylens-analytics")
    runtime = [d for d in dependencies if "extra ==" not in d]
    assert sorted(d.split("==")[0] for d in runtime) == ["duckdb", "scikit-learn", "sqlglot"]


def test_boolean_filters_are_supported():
    result, _ = execute(
        "SELECT COUNT(*) FROM orders WHERE channel = 'Web' AND (status = 'completed' OR NOT status = 'cancelled')"
    )
    assert result == [(1,)]


def test_unqualified_model_and_qualified_columns():
    result, plan = execute(
        "SELECT orders.order_id, orders.net_revenue FROM orders ORDER BY orders.order_id"
    )
    assert result == [(1, 15.0), (2, 0.0)]
    assert plan.models == ("orders",)
    assert plan.calculated_fields == ("orders.net_revenue",)


def test_join_aliases():
    result, plan = execute(
        "SELECT c.customer_name, SUM(o.net_revenue) FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.customer_name ORDER BY c.customer_name"
    )
    assert result == [("Quinn Kim", 0.0), ("Riley Shah", 15.0)]
    assert plan.models == ("customers", "orders")


def test_cte_shadowing_a_model_does_not_rewrite_the_cte_reference():
    result, plan = execute(
        "WITH orders AS (SELECT customer_id FROM customers) SELECT COUNT(*) FROM orders"
    )
    assert result == [(2,)]
    assert plan.models == ("customers",)


def test_chained_ctes():
    result, plan = execute(
        "WITH source AS (SELECT net_revenue FROM orders), totals AS (SELECT SUM(net_revenue) AS amount FROM source) SELECT amount FROM totals"
    )
    assert result == [(15.0,)]
    assert plan.models == ("orders",)


def test_self_join():
    result, _ = execute(
        "SELECT a.order_id, b.net_revenue FROM orders a JOIN orders b ON a.order_id = b.order_id ORDER BY a.order_id"
    )
    assert result == [(1, 15.0), (2, 0.0)]


def test_union_branches_share_the_compiled_model():
    result, _ = execute(
        "SELECT net_revenue FROM orders WHERE order_id = 1 UNION ALL SELECT net_revenue FROM orders WHERE order_id = 2"
    )
    assert result == [(15.0,), (0.0,)]


def test_quoted_case_insensitive_model():
    result, _ = execute('SELECT "ORDERS".net_revenue FROM "ORDERS" WHERE order_id = 1')
    assert result == [(15.0,)]


def test_reserved_cte_names_cannot_collide_with_compiler_names():
    with pytest.raises(QueryError, match="reserved"):
        QueryPlanner().compile(
            "WITH __ql_orders AS (SELECT order_id FROM orders) SELECT * FROM __ql_orders"
        )


def test_calculated_dependencies_are_sorted_before_compilation():
    registry = ModelRegistry(config())
    assert registry.models["sales"].calculated_order == ("net", "after_fee")
    rows, plan = execute("SELECT id, net, after_fee FROM sales ORDER BY id", registry)
    assert rows == [(1, 15.0, 13.0), (2, 30.0, 28.0)]
    assert plan.calculated_fields == ("sales.net", "sales.after_fee")


def test_calculated_dependency_cycles_are_rejected():
    definition = config()
    definition["models"]["sales"]["columns"]["net"]["expression"] = "after_fee + 2"
    with pytest.raises(QueryError, match="cycle"):
        ModelRegistry(definition)


def test_unknown_calculated_column_reference_is_rejected():
    definition = config()
    definition["models"]["sales"]["columns"]["net"]["expression"] = "gross - missing"
    with pytest.raises(QueryError, match="Unknown field"):
        ModelRegistry(definition)


@pytest.mark.parametrize(
    "expression", ["SELECT 1", "gross; DROP TABLE facts", "SUM(gross)", "ROW_NUMBER() OVER ()"]
)
def test_calculated_fields_must_be_scalar_expressions(expression):
    definition = config()
    definition["models"]["sales"]["columns"]["net"]["expression"] = expression
    with pytest.raises(QueryError):
        ModelRegistry(definition)


def test_model_fingerprint_tracks_definition_changes():
    first = config()
    second = deepcopy(first)
    second["models"]["sales"]["columns"]["net"]["expression"] = "gross - refund - 1"
    assert ModelRegistry(first).fingerprint != ModelRegistry(second).fingerprint


def test_planning_does_not_mutate_the_registry_or_other_queries():
    registry = get_registry()
    planner = QueryPlanner(registry)
    before = planner.compile("SELECT net_revenue FROM orders")
    planner.compile("SELECT customer_name FROM customers")
    after = planner.compile("SELECT net_revenue FROM orders")
    assert before == after


def test_physical_table_access_is_rejected_by_the_planner():
    with pytest.raises(QueryError, match="configured model"):
        QueryPlanner().compile("SELECT * FROM raw_orders")
