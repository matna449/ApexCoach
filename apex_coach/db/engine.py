"""Engine factory — takes a full database URL or a bare SQLite path.

SQLite does not enforce foreign keys by default; enforcement is a
per-connection setting, not a schema property, so PRAGMA foreign_keys=ON
fires on every SQLite connection. See docs/adr/0004.
"""

import sqlalchemy as sa
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy import event


def create_engine(database: str) -> Engine:
    url = make_url(database) if "://" in database else URL.create("sqlite", database=database)

    if url.get_backend_name() != "sqlite":
        # Small pool for serverless functions behind Neon's pooled URL. Its
        # connection pooler reuses server connections, so psycopg's automatic
        # prepared statements stay off.
        return sa.create_engine(
            url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
            connect_args={"prepare_threshold": None},
        )

    engine = sa.create_engine(url)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
