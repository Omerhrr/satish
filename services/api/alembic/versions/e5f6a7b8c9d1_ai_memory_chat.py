"""Satish AI: answer language, chat threads, memory

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d1"
down_revision: str | None = "d4e5f6a7b8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("language", sa.String(40), nullable=True))
        b.add_column(sa.Column("thread_id", sa.String(36), nullable=True))
        b.create_index("ix_tasks_thread_id", ["thread_id"])
    op.create_table(
        "ai_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.String(300), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_memories_user_id", "ai_memories", ["user_id"])
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_turns_user_id", "chat_turns", ["user_id"])
    op.create_index("ix_chat_turns_thread_id", "chat_turns", ["thread_id"])
    op.create_index("ix_chat_turns_created_at", "chat_turns", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_turns")
    op.drop_table("ai_memories")
    with op.batch_alter_table("tasks") as b:
        b.drop_index("ix_tasks_thread_id")
        b.drop_column("thread_id")
        b.drop_column("language")
