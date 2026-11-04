"""SQL boundary before QueryLens model expansion and read-only execution."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from querylens.catalog import SCHEMA
from querylens.errors import QueryError

ALLOWED_FUNCTIONS = {
    "and",
    "or",
    "not",
    "sum",
    "count",
    "avg",
    "min",
    "max",
    "round",
    "coalesce",
    "nullif",
    "if",
    "case",
    "cast",
    "trycast",
    "datetrunc",
    "timestamptrunc",
    "extract",
    "timetostr",
    "lower",
    "upper",
    "abs",
    "rownumber",
    "rank",
    "denserank",
    "lag",
    "lead",
}


def validate(sql, schema=None):
    schema = SCHEMA if schema is None else schema
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 12000:
        raise QueryError("Enter a SQL query of 1 to 12,000 characters.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except SqlglotError as error:
        raise QueryError(f"SQL could not be parsed: {error}") from error
    if len(statements) != 1 or not isinstance(
        statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)
    ):
        raise QueryError("Only one SELECT query is allowed.")
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 1500:
        raise QueryError("This query is too complex for the local workbench.")
    banned = {
        "insert",
        "update",
        "delete",
        "create",
        "drop",
        "alter",
        "copy",
        "command",
        "into",
        "merge",
        "transaction",
        "lock",
        "pragma",
        "set",
        "attach",
        "detach",
    }
    if any(node.key in banned for node in nodes):
        raise QueryError("Statements that change data or settings are not allowed.")
    for node in tree.find_all(exp.Func):
        if node.key.lower() not in ALLOWED_FUNCTIONS:
            raise QueryError(
                f"Function {node.sql_name() if not isinstance(node, exp.Anonymous) else node.name} is not approved for this workbench."
            )
    sources = set()
    for scope in traverse_scope(tree):
        for _, source in scope.sources.items():
            if isinstance(source, exp.Table):
                if source.catalog or source.db or source.name.lower() not in schema:
                    raise QueryError(
                        "Query only the configured model names, using unqualified table names."
                    )
                sources.add(source.name.lower())
        if scope.expression.args.get("with_") and scope.expression.args["with_"].args.get(
            "recursive"
        ):
            raise QueryError("Recursive queries are not supported.")
    if not sources:
        raise QueryError("The query must read at least one modeled table.")
    return tree.sql(dialect="duckdb"), sorted(sources)
