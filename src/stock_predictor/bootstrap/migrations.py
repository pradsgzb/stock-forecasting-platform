"""Controlled Alembic migration entry points using packaged migration assets."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine


def _packaged_script_location() -> Path:
    return Path(__file__).resolve().parents[1] / "db" / "migrations"


def alembic_config(
    database_url: str,
    *,
    script_location: Path | None = None,
) -> Config:
    location = script_location or _packaged_script_location()
    if not location.is_dir() or not (location / "env.py").is_file():
        raise FileNotFoundError(f"Alembic migration assets not found: {location}")
    config = Config()
    config.set_main_option("script_location", str(location))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str, *, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade_database(database_url: str, *, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)


def current_revision(database_url: str) -> str | None:
    """Return the database revision without emitting Alembic console output."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()
