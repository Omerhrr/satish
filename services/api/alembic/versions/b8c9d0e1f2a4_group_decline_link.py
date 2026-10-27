"""group payments: declined list and the Mini App link

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a4"
down_revision: str | None = "a7b8c9d0e1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_payments") as b:
        b.add_column(sa.Column("declined", sa.JSON(), nullable=True))
        b.add_column(sa.Column("pay_url", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_payments") as b:
        b.drop_column("pay_url")
        b.drop_column("declined")
