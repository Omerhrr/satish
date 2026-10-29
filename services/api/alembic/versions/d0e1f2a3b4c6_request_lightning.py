"""payment requests: Lightning invoice and forwarding

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
Create Date: 2026-10-29

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c6"
down_revision: str | None = "c9d0e1f2a3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_requests") as b:
        b.add_column(sa.Column("ln_invoice", sa.String(1024), nullable=True))
        b.add_column(sa.Column("ln_destination", sa.String(300), nullable=True))
        b.add_column(sa.Column("paid_via", sa.String(16), nullable=True))
        b.add_column(sa.Column("forward_status", sa.String(16), nullable=True))
        b.add_column(sa.Column("forward_ref", sa.String(128), nullable=True))
        b.add_column(sa.Column("forward_attempts", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("forward_error", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("payment_requests") as b:
        for c in ("forward_error", "forward_attempts", "forward_ref", "forward_status", "paid_via", "ln_destination", "ln_invoice"):
            b.drop_column(c)
