"""wallet payment alerts: opt-in settings and watched receive addresses

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_alert_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "network", name="uq_wallet_alert_user_network"),
    )
    op.create_index("ix_wallet_alert_settings_user_id", "wallet_alert_settings", ["user_id"])
    op.create_table(
        "watched_addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("seen", sa.JSON(), nullable=True),
        sa.Column("baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "address", name="uq_watched_user_address"),
    )
    op.create_index("ix_watched_addresses_user_id", "watched_addresses", ["user_id"])
    op.create_index("ix_watched_addresses_network", "watched_addresses", ["network"])


def downgrade() -> None:
    op.drop_index("ix_watched_addresses_network", table_name="watched_addresses")
    op.drop_index("ix_watched_addresses_user_id", table_name="watched_addresses")
    op.drop_table("watched_addresses")
    op.drop_index("ix_wallet_alert_settings_user_id", table_name="wallet_alert_settings")
    op.drop_table("wallet_alert_settings")
