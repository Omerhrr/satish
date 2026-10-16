"""phase-9: service_credentials, email_drafts, automation_runs, notifications + scheduled_jobs budget columns

Revision ID: f2a3b4c5d6e0
Revises: a9b0c1d2e3f4
Create Date: 2026-10-15

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e0"
down_revision: str | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # scheduled_jobs: budget totals + failure bookkeeping (phase 9)
    op.add_column(
        "scheduled_jobs", sa.Column("budget_total_xp", sa.Integer(), nullable=True)
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column("total_spent_xp", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_jobs", sa.Column("last_run_status", sa.String(length=48), nullable=True)
    )
    op.add_column(
        "scheduled_jobs", sa.Column("auto_paused_reason", sa.String(length=128), nullable=True)
    )

    # service_credentials: encrypted-at-rest credential per connection
    op.create_table(
        "service_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["connected_services.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", name="uq_service_credential_connection"),
    )
    op.create_index(
        "ix_service_credentials_connection_id", "service_credentials", ["connection_id"]
    )

    # email_drafts: preview-before-send email flow
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="drafted"),
        sa.Column("provider_mode", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_drafts_user_id", "email_drafts", ["user_id"])
    op.create_index("ix_email_drafts_task_id", "email_drafts", ["task_id"])
    op.create_index("ix_email_drafts_digest", "email_drafts", ["digest"])

    # automation_runs: one row per execution attempt
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("xp_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("xp_budget_per_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "run_number", name="uq_automation_run_number"),
    )
    op.create_index("ix_automation_runs_job_id", "automation_runs", ["job_id"])
    op.create_index("ix_automation_runs_user_id", "automation_runs", ["user_id"])
    op.create_index("ix_automation_runs_task_id", "automation_runs", ["task_id"])

    # notifications: condition-based, persisted, API-readable
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("relayed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_automation_runs_task_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_user_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_job_id", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_email_drafts_digest", table_name="email_drafts")
    op.drop_index("ix_email_drafts_task_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_user_id", table_name="email_drafts")
    op.drop_table("email_drafts")
    op.drop_index("ix_service_credentials_connection_id", table_name="service_credentials")
    op.drop_table("service_credentials")
    op.drop_column("scheduled_jobs", "auto_paused_reason")
    op.drop_column("scheduled_jobs", "last_run_status")
    op.drop_column("scheduled_jobs", "consecutive_failures")
    op.drop_column("scheduled_jobs", "run_count")
    op.drop_column("scheduled_jobs", "total_spent_xp")
    op.drop_column("scheduled_jobs", "budget_total_xp")
