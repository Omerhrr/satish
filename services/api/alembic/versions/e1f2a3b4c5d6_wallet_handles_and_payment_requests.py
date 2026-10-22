"""wallet handles (@usernames), signed address pools, payment requests

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-10-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_handles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("identity_pubkey", sa.String(66), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("network", "username", name="uq_handle_network_username"),
    )
    op.create_index("ix_wallet_handles_user_id", "wallet_handles", ["user_id"])
    op.create_table(
        "handle_addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("identity_pubkey", sa.String(66), nullable=False),
        sa.Column("address", sa.String(100), nullable=False, unique=True),
        sa.Column("derivation_index", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="available"),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_handle_addresses_user_id", "handle_addresses", ["user_id"])
    op.create_index("ix_handle_addresses_network", "handle_addresses", ["network"])
    op.create_index("ix_handle_addresses_status", "handle_addresses", ["status"])
    op.create_table(
        "payment_requests",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("signature", sa.String(160), nullable=False),
        sa.Column("identity_pubkey", sa.String(66), nullable=False),
        sa.Column("amount_sats", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(140), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("paid_sats", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_requests_user_id", "payment_requests", ["user_id"])
    op.create_index("ix_payment_requests_status", "payment_requests", ["status"])


def downgrade() -> None:
    op.drop_table("payment_requests")
    op.drop_table("handle_addresses")
    op.drop_table("wallet_handles")
