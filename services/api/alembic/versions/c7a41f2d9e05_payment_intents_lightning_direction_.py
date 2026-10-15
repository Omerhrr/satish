"""payment_intents: lightning direction/bolt11/fee/authorization columns

Revision ID: c7a41f2d9e05
Revises: b3384bc21604
Create Date: 2026-10-15 11:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c7a41f2d9e05'
down_revision = 'b3384bc21604'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('payment_intents', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('direction', sa.String(length=16), nullable=False,
                      server_default='receive')
        )
        batch_op.add_column(sa.Column('bolt11', sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column('fee_msat', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('authorization_digest', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('payment_intents', schema=None) as batch_op:
        batch_op.drop_column('authorization_digest')
        batch_op.drop_column('fee_msat')
        batch_op.drop_column('bolt11')
        batch_op.drop_column('direction')
