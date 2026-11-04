"""Scope-aware model expansion implemented for QueryLens using sqlglot ASTs."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from querylens.errors import QueryError
from querylens.modeling import PREFIX, get_registry
from querylens.policy import validate


@dataclass(frozen=True)
class CompiledQuery:
    query_sql: str
    executable_sql: str
    models: tuple[str, ...]
    calculated_fields: tuple[str, ...]
    model_version: str


class QueryPlanner:
    def __init__(self, registry=None):
        self.registry = registry or get_registry()

    def compile(self, sql):
        clean, _ = validate(sql, schema=self.registry.public_schema())
        tree = sqlglot.parse_one(clean, read="duckdb")
        if any(cte.alias_or_name.lower().startswith(PREFIX) for cte in tree.find_all(exp.CTE)):
            raise QueryError(f"CTE names starting with {PREFIX} are reserved.")
        models = set()
        # Scope.sources distinguishes physical model references from CTE names
        # and subquery aliases. Only the actual model Table nodes are rewritten.
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if not isinstance(source, exp.Table):
                    continue
                name = source.name.lower()
                models.add(name)
                if source.args.get("alias") is None:
                    source.set("alias", exp.TableAlias(this=source.this.copy()))
                source.set("this", exp.to_identifier(PREFIX + name, quoted=True))
        model_names = tuple(sorted(models))
        compiled_ctes = [
            exp.CTE(
                this=self.registry.compile_model(name),
                alias=exp.TableAlias(this=exp.to_identifier(PREFIX + name, quoted=True)),
            )
            for name in model_names
        ]
        existing = tree.args.get("with_")
        if existing is None:
            tree.set("with_", exp.With(expressions=compiled_ctes))
        else:
            existing.set("expressions", compiled_ctes + existing.expressions)
        calculated = tuple(
            f"{name}.{field}"
            for name in model_names
            for field in self.registry.models[name].calculated_order
        )
        return CompiledQuery(
            clean,
            tree.sql(dialect="duckdb", pretty=True),
            model_names,
            calculated,
            self.registry.fingerprint,
        )
