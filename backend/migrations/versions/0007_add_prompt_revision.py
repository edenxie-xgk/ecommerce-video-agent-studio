"""add workflow prompt revision

Revision ID: 0007_prompt_revision
Revises: 0006_preserve_run_history
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_prompt_revision"
down_revision = "0006_preserve_run_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为分镜编辑增加数据库级乐观锁版本。"""

    op.add_column(
        "workflow_runs",
        sa.Column("prompt_revision", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """移除分镜编辑版本列。"""

    op.drop_column("workflow_runs", "prompt_revision")
