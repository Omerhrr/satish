"""research_sources - durable provenance for research tasks (phase 7)

Revision ID: a9b0c1d2e3f4
Revises: e5f6a7b8c9d0
Create Date: 2026-10-15

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b0c1d2e3f4"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=16), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("task_id", "url", name="uq_research_source_task_url"),
    )
    op.create_index(
        "ix_research_sources_task_id", "research_sources", ["task_id"], unique=False
    )
    op.create_index(
        "ix_research_sources_user_id", "research_sources", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_research_sources_user_id", table_name="research_sources")
    op.drop_index("ix_research_sources_task_id", table_name="research_sources")
    op.drop_table("research_sources")
