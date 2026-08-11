from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
import shutil

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.resolved_database_url,
    connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
)


if settings.resolved_database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_database() -> None:
    """Bring both fresh and pre-Alembic installations to the current schema.

    v0.1 created tables with ``create_all``.  Before stamping that known
    schema, make a local SQLite copy so a failed or interrupted upgrade is
    recoverable.  New databases run the complete Alembic history normally.
    """
    _upgrade_database()
    from . import models  # noqa: F401  # keep third-party/custom tables harmless

    Base.metadata.create_all(engine)
    from .seed import seed_database

    with SessionLocal.begin() as session:
        seed_database(session)


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    return config


def _sqlite_file() -> Path | None:
    url = settings.resolved_database_url
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        return None
    return Path(url.removeprefix("sqlite:///"))


def _backup_legacy_database() -> Path | None:
    source = _sqlite_file()
    if not source or not source.exists():
        return None
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"pre-migration-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{source.name}"
    shutil.copy2(source, target)
    return target


def _upgrade_database() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "alembic_version" not in table_names and table_names:
        _backup_legacy_database()
        # Existing versions were all created from the v0.1 metadata.  Stamping
        # avoids replaying CREATE TABLE statements over user data.
        command.stamp(_alembic_config(), "0001_baseline")
    command.upgrade(_alembic_config(), "head")
