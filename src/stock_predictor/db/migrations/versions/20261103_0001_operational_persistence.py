"""Create operational audit, outbox, idempotency, paper, and SLO tables.

Revision ID: 20261103_0001
Revises: None
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decimal_type() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "sqlite":
        return sa.String(80)
    return sa.Numeric(38, 18)


def upgrade() -> None:
    decimal_type = _decimal_type()
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("request_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_audit_sequence_positive"),
        sa.UniqueConstraint("sequence", name="uq_audit_sequence"),
        sa.UniqueConstraint("event_hash", name="uq_audit_hash"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("aggregate_type", sa.String(128), nullable=False),
        sa.Column("aggregate_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("causation_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("event_version > 0", name="ck_outbox_version_positive"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["status", "available_at"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("principal_id", sa.String(255), primary_key=True),
        sa.Column("operation", sa.String(128), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.CheckConstraint("revision > 0", name="ck_idempotency_revision_positive"),
        sa.UniqueConstraint(
            "principal_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_identity",
        ),
    )
    op.create_index(
        "ix_idempotency_expiry",
        "idempotency_records",
        ["expires_at"],
    )
    op.create_table(
        "paper_accounts",
        sa.Column("account_id", sa.String(36), primary_key=True),
        sa.Column("owner_subject", sa.String(255), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cash_amount", decimal_type, nullable=False),
        sa.Column("realized_pnl_amount", decimal_type, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cash_amount >= 0", name="ck_paper_cash_nonnegative"),
        sa.CheckConstraint("revision > 0", name="ck_paper_revision_positive"),
    )
    op.create_index(
        "ix_paper_accounts_owner",
        "paper_accounts",
        ["owner_subject"],
    )
    op.create_table(
        "paper_positions",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("instrument_id", sa.String(36), primary_key=True),
        sa.Column("quantity", decimal_type, nullable=False),
        sa.Column("average_price", decimal_type, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_paper_position_quantity_positive",
        ),
    )
    op.create_table(
        "paper_orders",
        sa.Column("order_id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(36), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", decimal_type, nullable=False),
        sa.Column("reference_price", decimal_type, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "idempotency_key",
            name="uq_paper_order_idempotency",
        ),
    )
    op.create_index(
        "ix_paper_orders_account_submitted",
        "paper_orders",
        ["account_id", "submitted_at"],
    )
    op.create_table(
        "paper_fills",
        sa.Column("fill_id", sa.String(36), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(36),
            sa.ForeignKey("paper_orders.order_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("instrument_id", sa.String(36), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", decimal_type, nullable=False),
        sa.Column("reference_price", decimal_type, nullable=False),
        sa.Column("execution_price", decimal_type, nullable=False),
        sa.Column("gross_notional", decimal_type, nullable=False),
        sa.Column("commission", decimal_type, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_paper_fill_order"),
    )
    op.create_table(
        "slo_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("objective_name", sa.String(128), nullable=False),
        sa.Column("indicator", sa.String(32), nullable=False),
        sa.Column("target", decimal_type, nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("latency_threshold_ms", decimal_type, nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_events", sa.BigInteger(), nullable=False),
        sa.Column("good_events", sa.BigInteger(), nullable=False),
        sa.Column("measured_value", decimal_type, nullable=False),
        sa.Column("error_budget_remaining", decimal_type, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_slo_fingerprint"),
    )
    op.create_index(
        "ix_slo_objective_created",
        "slo_snapshots",
        ["objective_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_slo_objective_created", table_name="slo_snapshots")
    op.drop_table("slo_snapshots")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_account_submitted", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_accounts_owner", table_name="paper_accounts")
    op.drop_table("paper_accounts")
    op.drop_index("ix_idempotency_expiry", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("audit_events")
