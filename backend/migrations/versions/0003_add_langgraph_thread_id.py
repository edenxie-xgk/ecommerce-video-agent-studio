"""为创意运行增加 LangGraph thread_id。

Revision ID: 0003_langgraph_thread
Revises: 0002_creative_runs
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_langgraph_thread"
down_revision: str | None = "0002_creative_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creative_runs",
        sa.Column("thread_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE creative_runs "
            "SET thread_id = 'legacy-' || CAST(id AS VARCHAR) "
            "WHERE thread_id IS NULL"
        )
    )
    with op.batch_alter_table("creative_runs") as batch_op:
        batch_op.alter_column(
            "thread_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_index(
            "ix_creative_runs_thread_id",
            ["thread_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("creative_runs") as batch_op:
        batch_op.drop_index("ix_creative_runs_thread_id")
        batch_op.drop_column("thread_id")
