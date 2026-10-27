"""group payments (pay / split cards in Telegram groups)

Revision ID: a7b8c9d0e1f3
Revises: f6a7b8c9d0e2
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f3"
down_revision: str | None = "f6a7b8c9d0e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_payments",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("creator_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_username", sa.String(32), nullable=False),
        sa.Column("amount_sats", sa.BigInteger(), nullable=False),
        sa.Column("display", sa.String(64), nullable=False),
        sa.Column("note", sa.String(140), nullable=True),
        sa.Column("participants", sa.JSON(), nullable=True),
        sa.Column("paid", sa.JSON(), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("group_payments")
