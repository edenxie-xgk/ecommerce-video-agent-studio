"""隔离旧版本未实际保存文件的商品图片记录。

Revision ID: 0004_verified_assets
Revises: 0003_langgraph_thread
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_verified_assets"
down_revision: str | None = "0003_langgraph_thread"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """旧版本没有落盘文件，不能继续把其记录视为 Agent 图片证据。"""

    op.execute(
        sa.text(
            "UPDATE project_assets "
            "SET asset_type = 'legacy_unverified_image' "
            "WHERE asset_type = 'product_image'"
        )
    )


def downgrade() -> None:
    """恢复旧版本对历史素材类型的命名。"""

    op.execute(
        sa.text(
            "UPDATE project_assets "
            "SET asset_type = 'product_image' "
            "WHERE asset_type = 'legacy_unverified_image'"
        )
    )
