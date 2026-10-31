"""Dialect-dispatched INSERT for upserts.

SQLite and Postgres share the `on_conflict_do_update(index_elements=...,
set_=...)` API, but each needs its own dialect's `insert` construct.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

_INSERT_BY_DIALECT = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}


def dialect_insert(engine: sa.engine.Engine, table: sa.Table):
    return _INSERT_BY_DIALECT[engine.dialect.name](table)
