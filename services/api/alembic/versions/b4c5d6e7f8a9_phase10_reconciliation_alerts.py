"""phase-10: reconciliation_alerts (operator-facing payment discrepancy queue)

Revision ID: b4c5d6e7f8a9
Revises: f2a3b4c5d6e0
Create Date: 2026-10-16

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "f2a3b4c5d6e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=72), nullable=False),
        sa.Column("expected", sa.String(length=64), nullable=True),
        sa.Column("observed", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_note", sa.String(length=280), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_alerts_kind", "reconciliation_alerts", ["kind"], unique=False
    )
    op.create_index(
        "ix_reconciliation_alerts_subject", "reconciliation_alerts", ["subject"], unique=False
    )
    op.create_index(
        "ix_reconciliation_alerts_status", "reconciliation_alerts", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_alerts_status", table_name="reconciliation_alerts")
    op.drop_index("ix_reconciliation_alerts_subject", table_name="reconciliation_alerts")
    op.drop_index("ix_reconciliation_alerts_kind", table_name="reconciliation_alerts")
    op.drop_table("reconciliation_alerts")

