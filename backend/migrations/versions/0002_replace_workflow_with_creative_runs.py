"""用单一创意决策运行替换旧 LangGraph 测试表。

Revision ID: 0002_creative_runs
Revises: 0001_initial_workflow_tables
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_creative_runs"
down_revision: str | None = "0001_initial_workflow_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("video_projects.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider_key", sa.String(), nullable=False),
        sa.Column("model_key", sa.String(), nullable=True),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_creative_runs_project_id",
        "creative_runs",
        ["project_id"],
    )
    op.drop_table("agent_runs")
    op.drop_table("workflow_node_runs")
    op.drop_table("workflow_runs")


def downgrade() -> None:
    raise RuntimeError(
        "The obsolete workflow test tables are intentionally not recreated."
    )
