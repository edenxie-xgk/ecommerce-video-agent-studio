"""恢复工作流运行、节点运行和 AgentRun 业务记录。

Revision ID: 0005_restore_workflow
Revises: 0004_verified_assets
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_restore_workflow"
down_revision: str | None = "0004_verified_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """重新创建以 WorkflowRun 为中心的工作流追踪表。"""

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("video_projects.id"), nullable=False),
        sa.Column("checkpoint_thread_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_node", sa.String(), nullable=True),
        sa.Column("pending_confirmation", sa.Boolean(), nullable=False),
        sa.Column("workflow_status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_workflow_runs_project_id", "workflow_runs", ["project_id"])
    op.create_index(
        "ix_workflow_runs_checkpoint_thread_id",
        "workflow_runs",
        ["checkpoint_thread_id"],
        unique=True,
    )

    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("video_projects.id"), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("review_run_id", sa.Integer(), nullable=True),
        sa.Column("generation_task_id", sa.Integer(), nullable=True),
        sa.Column("output_ref_type", sa.String(), nullable=True),
        sa.Column("output_ref_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_workflow_node_runs_workflow_run_id", "workflow_node_runs", ["workflow_run_id"])
    op.create_index("ix_workflow_node_runs_project_id", "workflow_node_runs", ["project_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("video_projects.id"), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column(
            "workflow_node_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_node_runs.id"),
            nullable=True,
        ),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider_key", sa.String(), nullable=True),
        sa.Column("model_key", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_runs_project_id", "agent_runs", ["project_id"])
    op.create_index("ix_agent_runs_workflow_run_id", "agent_runs", ["workflow_run_id"])


def downgrade() -> None:
    """移除恢复后的工作流追踪表。"""

    op.drop_index("ix_agent_runs_workflow_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_project_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_workflow_node_runs_project_id", table_name="workflow_node_runs")
    op.drop_index("ix_workflow_node_runs_workflow_run_id", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_runs_checkpoint_thread_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
