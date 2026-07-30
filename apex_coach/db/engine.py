"""Engine factory — fires PRAGMA foreign_keys=ON on every SQLite connection.

SQLite does not enforce foreign keys by default; enforcement is a
per-connection setting, not a schema property. See docs/adr/0004.
"""

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy import event


def create_engine(db_path: str) -> Engine:
    engine = sa.create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
