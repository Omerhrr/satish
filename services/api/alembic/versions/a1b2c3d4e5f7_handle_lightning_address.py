"""@username Lightning (Spark) address, signed by the wallet identity key

Revision ID: a1b2c3d4e5f7
Revises: f3a4b5c6d7e8
Create Date: 2026-10-23

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("wallet_handles") as b:
        b.add_column(sa.Column("spark_address", sa.String(300), nullable=True))
        b.add_column(sa.Column("spark_signature", sa.String(160), nullable=True))
        b.add_column(sa.Column("spark_network", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wallet_handles") as b:
        b.drop_column("spark_network")
        b.drop_column("spark_signature")
        b.drop_column("spark_address")
