"""Database engine, session management, and schema initialization.

SQLite is the only supported dialect. Schema ownership sits with Alembic; this
module only wires the engine and provides a session-scope dependency for
FastAPI routes plus a raw initializer used by tests.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from . import config

Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_db() -> None:
    """Create tables if they do not exist (test/dev convenience).

    In normal operation Alembic owns the schema; this only guarantees a
    usable DB for tests that bypass migrations.
    """
    from . import models  # noqa: F401  (register tables with SQLModel metadata)

    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session bound to this engine."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class DependsSession:
    """FastAPI dependency yielding a scoped database session."""

    def __call__(self) -> Generator[Session, None, None]:
        with session_scope() as session:
            yield session
