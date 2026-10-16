"""phase-9 KL-06: notification relay columns (one push decision per notification)

Revision ID: d8e9f0a1b2c3
Revises: b4c5d6e7f8a9
Create Date: 2026-10-16

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("relay_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("relay_detail", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "relay_detail")
    op.drop_column("notifications", "relay_status")
