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

    connection = op.get_bind()
    assets = sa.Table("project_assets", sa.MetaData(), autoload_with=connection)
    rows = connection.execute(
        sa.select(assets.c.id, assets.c["metadata"]).where(
            assets.c.asset_type == "product_image"
        )
    ).mappings()
    unverified_ids = [
        row["id"]
        for row in rows
        if not isinstance(row["metadata"], dict) or row["metadata"].get("verified") is not True
    ]
    if unverified_ids:
        connection.execute(
            assets.update()
            .where(assets.c.id.in_(unverified_ids))
            .values(asset_type="legacy_unverified_image")
        )

    _ensure_unique_thread_index(connection)


def _ensure_unique_thread_index(connection: sa.Connection) -> None:
    indexes = sa.inspect(connection).get_indexes("creative_runs")
    thread_index = next(
        (index for index in indexes if index.get("name") == "ix_creative_runs_thread_id"),
        None,
    )
    if thread_index and thread_index.get("unique"):
        return
    if thread_index:
        op.drop_index("ix_creative_runs_thread_id", table_name="creative_runs")
    op.create_index(
        "ix_creative_runs_thread_id",
        "creative_runs",
        ["thread_id"],
        unique=True,
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
