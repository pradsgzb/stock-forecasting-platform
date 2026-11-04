from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from stock_predictor.bootstrap.migrations import (
    alembic_config,
    current_revision,
    downgrade_database,
    upgrade_database,
)

pytestmark = pytest.mark.integration


def test_packaged_migrations_upgrade_report_and_downgrade(tmp_path) -> None:
    database = tmp_path / "migrated.db"
    url = f"sqlite+pysqlite:///{database}"

    upgrade_database(url)

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "audit_events",
        "outbox_events",
        "idempotency_records",
        "paper_accounts",
        "paper_positions",
        "paper_orders",
        "paper_fills",
        "slo_snapshots",
    } <= tables
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "20261103_0001"

    assert current_revision(url) == "20261103_0001"

    downgrade_database(url, revision="base")
    assert current_revision(url) is None
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_migration_configuration_rejects_missing_assets(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="assets"):
        alembic_config("sqlite+pysqlite:///:memory:", script_location=Path(tmp_path))
