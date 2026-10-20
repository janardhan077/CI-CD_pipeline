"""
Database engine and session management - shared by every microservice.

All services point at the SAME database_url (shared-DB split). SQLite is
used with WAL mode so multiple service *processes* can read concurrently
and writers don't starve readers; each service only ever writes to the
table(s) it owns (see README ownership map), so writer contention across
services is rare (e.g. a sale only writes to `sales`; only the Ledger
service writes to `ledger_transactions`).

Moving to Postgres later is a one-line change (INON_DATABASE_URL) - no
other code in any service should know or care that it's SQLite.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from common.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """WAL mode + foreign keys, on every new connection from every service."""
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")  # wait up to 10s on writer contention
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency - one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (every model, regardless of which service owns
    it) if they don't exist yet. Safe to call from every service on
    startup - CREATE TABLE IF NOT EXISTS is idempotent, and this is what
    lets each service run independently against a fresh shared DB
    without needing a separate 'migrator' service for local dev.
    Production should use Alembic against the shared DB instead."""
    from common import models  # noqa: F401  (ensures all models are registered)
    if engine.dialect.name == "postgresql":
        # Several services boot at once against the same Postgres; a
        # session-level advisory lock makes the first one create the
        # schema while the others wait, avoiding "type already exists".
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(727274)"))
            try:
                Base.metadata.create_all(bind=conn)
                conn.commit()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(727274)"))
                conn.commit()
    else:
        Base.metadata.create_all(bind=engine)
