"""initial schema: 16 tables

Revision ID: 414fb4b2ccf0
Revises:
Create Date: 2026-10-14 18:02:53.820300
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '414fb4b2ccf0'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('actor_type', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('metadata_redacted', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index('ix_audit_event_resource', ['event_type', 'resource_type', 'resource_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_event_type'), ['event_type'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('connected_services',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=True),
    sa.Column('credential_reference', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('connected_services', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_connected_services_user_id'), ['user_id'], unique=False)

    op.create_table('payment_intents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('provider_reference', sa.String(length=191), nullable=True),
    sa.Column('amount_sats', sa.BigInteger(), nullable=False),
    sa.Column('xp_amount', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('settled_at', sa.DateTime(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=191), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key'),
    sa.UniqueConstraint('provider_reference')
    )
    with op.batch_alter_table('payment_intents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payment_intents_user_id'), ['user_id'], unique=False)

    op.create_table('scheduled_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('task_template', sa.JSON(), nullable=True),
    sa.Column('schedule', sa.String(length=128), nullable=False),
    sa.Column('conditions', sa.JSON(), nullable=True),
    sa.Column('budget_per_run_xp', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('next_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('scheduled_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scheduled_jobs_user_id'), ['user_id'], unique=False)

    op.create_table('sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('budget_xp', sa.Integer(), nullable=False),
    sa.Column('reserved_xp', sa.Integer(), nullable=False),
    sa.Column('actual_xp', sa.Integer(), nullable=False),
    sa.Column('deliverable', sa.String(length=255), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tasks_user_id'), ['user_id'], unique=False)

    op.create_table('telegram_accounts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('linked_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('telegram_user_id')
    )
    with op.batch_alter_table('telegram_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_accounts_user_id'), ['user_id'], unique=False)

    op.create_table('wallets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('wallet_type', sa.String(length=32), nullable=False),
    sa.Column('network', sa.String(length=16), nullable=False),
    sa.Column('public_descriptor_or_reference', sa.Text(), nullable=True),
    sa.Column('label', sa.String(length=128), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('wallets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wallets_user_id'), ['user_id'], unique=False)

    op.create_table('xp_accounts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('balance', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('balance >= 0', name='ck_xp_balance_nonnegative'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('xp_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_xp_accounts_user_id'), ['user_id'], unique=True)

    op.create_table('xp_ledger_entries',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('entry_type', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('balance_after', sa.Integer(), nullable=False),
    sa.Column('reference_type', sa.String(length=32), nullable=True),
    sa.Column('reference_id', sa.String(length=64), nullable=True),
    sa.Column('note', sa.String(length=512), nullable=True),
    sa.Column('idempotency_key', sa.String(length=191), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("amount != 0 OR entry_type = 'charge'", name='ck_ledger_amount'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    with op.batch_alter_table('xp_ledger_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_xp_ledger_entries_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_xp_ledger_entries_user_id'), ['user_id'], unique=False)

    op.create_table('approvals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('action_type', sa.String(length=64), nullable=False),
    sa.Column('action_digest', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('approvals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approvals_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_user_id'), ['user_id'], unique=False)

    op.create_table('artifacts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('object_key', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('object_key')
    )
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_artifacts_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifacts_user_id'), ['user_id'], unique=False)

    op.create_table('task_steps',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('step_index', sa.Integer(), nullable=False),
    sa.Column('tool_name', sa.String(length=128), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('input_reference', sa.String(length=255), nullable=True),
    sa.Column('output_reference', sa.String(length=255), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'step_index', name='uq_task_step_index')
    )
    with op.batch_alter_table('task_steps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_task_steps_task_id'), ['task_id'], unique=False)

    op.create_table('wallet_addresses',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('wallet_id', sa.String(length=36), nullable=True),
    sa.Column('address', sa.String(length=128), nullable=False),
    sa.Column('alias', sa.String(length=128), nullable=True),
    sa.Column('network', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('address', 'network', name='uq_address_network')
    )
    with op.batch_alter_table('wallet_addresses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wallet_addresses_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_wallet_addresses_wallet_id'), ['wallet_id'], unique=False)

    op.create_table('wallet_transactions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('wallet_id', sa.String(length=36), nullable=False),
    sa.Column('transaction_reference', sa.String(length=128), nullable=True),
    sa.Column('transaction_type', sa.String(length=32), nullable=False),
    sa.Column('amount_sats', sa.BigInteger(), nullable=False),
    sa.Column('fee_sats', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('raw_metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('wallet_transactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wallet_transactions_transaction_reference'), ['transaction_reference'], unique=False)
        batch_op.create_index(batch_op.f('ix_wallet_transactions_wallet_id'), ['wallet_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('wallet_transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_wallet_transactions_wallet_id'))
        batch_op.drop_index(batch_op.f('ix_wallet_transactions_transaction_reference'))

    op.drop_table('wallet_transactions')
    with op.batch_alter_table('wallet_addresses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_wallet_addresses_wallet_id'))
        batch_op.drop_index(batch_op.f('ix_wallet_addresses_user_id'))

    op.drop_table('wallet_addresses')
    with op.batch_alter_table('task_steps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_steps_task_id'))

    op.drop_table('task_steps')
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_artifacts_user_id'))
        batch_op.drop_index(batch_op.f('ix_artifacts_task_id'))

    op.drop_table('artifacts')
    with op.batch_alter_table('approvals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approvals_user_id'))
        batch_op.drop_index(batch_op.f('ix_approvals_task_id'))

    op.drop_table('approvals')
    with op.batch_alter_table('xp_ledger_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_xp_ledger_entries_user_id'))
        batch_op.drop_index(batch_op.f('ix_xp_ledger_entries_created_at'))

    op.drop_table('xp_ledger_entries')
    with op.batch_alter_table('xp_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_xp_accounts_user_id'))

    op.drop_table('xp_accounts')
    with op.batch_alter_table('wallets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_wallets_user_id'))

    op.drop_table('wallets')
    with op.batch_alter_table('telegram_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_accounts_user_id'))

    op.drop_table('telegram_accounts')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tasks_user_id'))

    op.drop_table('tasks')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_sessions_token_hash'))

    op.drop_table('sessions')
    with op.batch_alter_table('scheduled_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scheduled_jobs_user_id'))

    op.drop_table('scheduled_jobs')
    with op.batch_alter_table('payment_intents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_intents_user_id'))

    op.drop_table('payment_intents')
    with op.batch_alter_table('connected_services', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_connected_services_user_id'))

    op.drop_table('connected_services')
    op.drop_table('users')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_audit_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_events_actor_id'))
        batch_op.drop_index('ix_audit_event_resource')

    op.drop_table('audit_events')
