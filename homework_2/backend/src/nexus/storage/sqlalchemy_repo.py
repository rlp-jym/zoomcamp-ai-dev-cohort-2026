"""SQLAlchemy preferences repository (database adapter).

One table, two columns, created with ``Base.metadata.create_all()`` at
startup. No Alembic, no pool tuning, no query layer beyond the three
``PreferencesRepository`` methods.

Synchronous by design: the JSON adapter is sync, both operations are
microseconds against a local database, and mixing one async adapter with
one sync adapter would complicate every caller for no measurable gain.
If reads ever leave the local machine, revisit this with an async engine.
"""

from pathlib import Path

from sqlalchemy import Engine, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    """Declarative base; tables are created via ``Base.metadata.create_all``."""


class PreferenceRow(Base):
    __tablename__ = "preferences"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


class SqlAlchemyPreferencesRepository:
    """Preferences stored as rows; identical behavior to the JSON adapter."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, key: str) -> str | None:
        with Session(self._engine) as session:
            row = session.get(PreferenceRow, key)
            return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        with Session(self._engine) as session:
            row = session.get(PreferenceRow, key)
            if row is None:
                session.add(PreferenceRow(key=key, value=value))
            else:
                row.value = value
            session.commit()

    def all(self) -> dict[str, str]:
        with Session(self._engine) as session:
            rows = session.scalars(select(PreferenceRow)).all()
            return {row.key: row.value for row in rows}


def default_engine(database_url: str) -> Engine:
    """Build an engine, creating the SQLite parent directory if needed.

    Relative SQLite paths resolve against the current working directory,
    exactly as SQLAlchemy itself resolves them; the directory is created
    so SQLite does not fail with "unable to open database file".
    """
    ensure_sqlite_directory(database_url)
    return create_engine(database_url)


def sqlite_file_path(database_url: str) -> Path | None:
    """Absolute filesystem path for a file-backed SQLite URL, if any.

    Relative paths resolve against the current working directory, exactly
    as SQLAlchemy itself resolves them. Returns None for in-memory and
    non-SQLite URLs.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    path = database_url[len(prefix) :]
    if path in ("", ":memory:"):
        return None
    target = Path(path)
    return target if target.is_absolute() else Path.cwd() / target


def ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL, if any."""
    target = sqlite_file_path(database_url)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
