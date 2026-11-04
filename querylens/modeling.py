"""QueryLens declarative model registry.

Physical fields form a base projection. Calculated fields form a dependency DAG;
the registry validates references and orders them before SQL compilation.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from querylens.errors import QueryError

NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
TYPES = {"INTEGER", "BIGINT", "DOUBLE", "VARCHAR", "DATE", "TIMESTAMP", "BOOLEAN"}
PREFIX = "__ql_"


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str
    expression: str | None = None


@dataclass(frozen=True)
class Model:
    name: str
    source: str
    description: str
    primary_key: str
    fields: tuple[Field, ...]
    calculated_order: tuple[str, ...]

    @property
    def columns(self):
        return {field.name: field.dtype for field in self.fields}


class ModelRegistry:
    def __init__(self, config):
        if not isinstance(config, dict) or config.get("version") != 1:
            raise QueryError("Model configuration must use version 1.")
        definitions = config.get("models")
        if not isinstance(definitions, dict) or not definitions:
            raise QueryError("Define at least one model.")
        models = {}
        for name, definition in definitions.items():
            self._name(name)
            if not isinstance(definition, dict):
                raise QueryError(f"Invalid definition for model {name}.")
            source = definition.get("source")
            self._name(source)
            columns = definition.get("columns")
            if not isinstance(columns, dict) or not columns:
                raise QueryError(f"Model {name} needs columns.")
            fields = []
            dependencies = {}
            for column, spec in columns.items():
                self._name(column)
                if not isinstance(spec, dict) or spec.get("type") not in TYPES:
                    raise QueryError(f"Invalid type for {name}.{column}.")
                expression = spec.get("expression")
                if expression is not None:
                    if not isinstance(expression, str) or not expression.strip():
                        raise QueryError(f"Invalid expression for {name}.{column}.")
                    try:
                        parts = [
                            p for p in sqlglot.parse(expression, read="duckdb") if p is not None
                        ]
                    except SqlglotError as error:
                        raise QueryError(f"Invalid expression for {name}.{column}.") from error
                    if len(parts) != 1 or not isinstance(parts[0], exp.Expression):
                        raise QueryError(f"Use one expression for {name}.{column}.")
                    ast = parts[0]
                    if any(
                        isinstance(
                            n,
                            (
                                exp.Query,
                                exp.DDL,
                                exp.DML,
                                exp.Table,
                                exp.Command,
                                exp.AggFunc,
                                exp.Window,
                            ),
                        )
                        for n in ast.walk()
                    ):
                        raise QueryError(
                            "Calculated fields must be scalar expressions, not queries or statements."
                        )
                    refs = set()
                    for ref in ast.find_all(exp.Column):
                        if ref.table or ref.db or ref.catalog or ref.name not in columns:
                            raise QueryError(f"Unknown field {ref.sql()} in {name}.{column}.")
                        refs.add(ref.name)
                    dependencies[column] = refs
                fields.append(Field(column, spec["type"], expression))
            if not any(f.expression is None for f in fields):
                raise QueryError(f"Model {name} needs at least one physical column.")
            key = definition.get("primary_key")
            if key not in columns:
                raise QueryError(f"Model {name} needs a valid primary_key.")
            order, visiting, done = [], set(), set()

            def visit(field):
                if field in visiting:
                    raise QueryError(f"Calculated-field cycle in {name}: {field}.")
                if field in done or field not in dependencies:
                    return
                visiting.add(field)
                for dependency in sorted(dependencies[field]):
                    visit(dependency)
                visiting.remove(field)
                done.add(field)
                order.append(field)

            for column in dependencies:
                visit(column)
            description = definition.get("description", "")
            if not isinstance(description, str):
                raise QueryError(f"Invalid description for {name}.")
            models[name] = Model(name, source, description, key, tuple(fields), tuple(order))
        self.models = MappingProxyType(models)
        self.fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[
            :16
        ]

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise QueryError("Model, source, and column names must be lowercase SQL identifiers.")

    def public_schema(self):
        return {
            name: {"description": model.description, "columns": model.columns}
            for name, model in self.models.items()
        }

    def compile_model(self, name):
        model = self.models[name]
        fields = {f.name: f for f in model.fields}
        physical = [f for f in model.fields if f.expression is None]
        base = exp.select(
            *[
                exp.alias_(
                    exp.Cast(
                        this=exp.column(f.name, quoted=True),
                        to=exp.DataType.build(f.dtype, dialect="duckdb"),
                    ),
                    f.name,
                    quoted=True,
                )
                for f in physical
            ]
        ).from_(exp.to_table(model.source, quoted=True))
        for column in model.calculated_order:
            field = fields[column]
            expression = sqlglot.parse_one(field.expression, read="duckdb")
            base = exp.select(
                "*",
                exp.alias_(
                    exp.Cast(this=expression, to=exp.DataType.build(field.dtype, dialect="duckdb")),
                    column,
                    quoted=True,
                ),
            ).from_(base.subquery(alias=PREFIX + "base"))
        return exp.select(*[exp.column(f.name, quoted=True) for f in model.fields]).from_(
            base.subquery(alias=PREFIX + "model")
        )


@lru_cache(maxsize=1)
def get_registry():
    return ModelRegistry(json.loads(files("querylens").joinpath("models.json").read_text()))
