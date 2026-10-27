"""device_links: browser-extension sign-in by bot code

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c0"
down_revision: str | None = "c3d4e5f6a7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("poll_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_device_links_code", "device_links", ["code"])


def downgrade() -> None:
    op.drop_index("ix_device_links_code", table_name="device_links")
    op.drop_table("device_links")
