from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector

from app.core.config import ensure_local_var_dir, get_settings


# backend 包根目录，用来定位 alembic.ini。
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 早期本地库可能没有 Alembic 版本记录，但已经具备首版业务表。
LEGACY_BASE_REVISION = "0001_initial_workflow_tables"
CREATIVE_RUN_BASE_REVISION = "0002_creative_runs"
CREATIVE_RUN_THREAD_REVISION = "0003_langgraph_thread"
VERIFIED_ASSET_REVISION = "0004_verified_assets"

# 如果这些首版业务表都存在，就可以把旧库安全标记到 LEGACY_BASE_REVISION。
INITIAL_BUSINESS_TABLES = {
    "agent_runs",
    "product_briefs",
    "project_assets",
    "video_projects",
    "workflow_node_runs",
    "workflow_runs",
}

# 曾经有一版把工作流表压缩成 creative_runs，未打版本号的本地库要从该版本继续迁移。
SIMPLIFIED_CREATIVE_RUN_TABLES = {
    "creative_runs",
    "product_briefs",
    "project_assets",
    "video_projects",
}


def upgrade_business_database() -> None:
    """执行业务数据库 Alembic 迁移。"""

    ensure_local_var_dir()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    _stamp_existing_initial_schema(config)
    command.upgrade(config, "head")


def _stamp_existing_initial_schema(config: Config) -> None:
    """兼容早期 create_all 生成、但未记录 Alembic head 的本地数据库。"""

    database_url = get_settings().database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    revision_to_stamp: str | None = None

    with engine.connect() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())

        has_initial_tables = INITIAL_BUSINESS_TABLES.issubset(table_names)
        has_simplified_tables = SIMPLIFIED_CREATIVE_RUN_TABLES.issubset(table_names)
        if not has_initial_tables and not has_simplified_tables:
            return

        if "alembic_version" not in table_names:
            revision_to_stamp = _detect_existing_revision(
                connection,
                inspector,
                has_initial_tables=has_initial_tables,
            )
        else:
            current_versions = list(
                connection.execute(text("select version_num from alembic_version"))
            )
            if not current_versions:
                revision_to_stamp = _detect_existing_revision(
                    connection,
                    inspector,
                    has_initial_tables=has_initial_tables,
                )

    # 先关闭检查连接，再由 Alembic 建立自己的写连接，避免 SQLite 锁等待。
    if revision_to_stamp:
        command.stamp(config, revision_to_stamp)


def _detect_existing_revision(
    connection: Connection,
    inspector: Inspector,
    *,
    has_initial_tables: bool,
) -> str:
    if has_initial_tables:
        return LEGACY_BASE_REVISION

    creative_columns = {column["name"] for column in inspector.get_columns("creative_runs")}
    if "thread_id" not in creative_columns:
        return CREATIVE_RUN_BASE_REVISION
    if not _has_unique_thread_index(inspector) or _has_unverified_product_images(connection):
        return CREATIVE_RUN_THREAD_REVISION
    return VERIFIED_ASSET_REVISION


def _has_unique_thread_index(inspector: Inspector) -> bool:
    return any(
        index.get("unique") and index.get("column_names") == ["thread_id"]
        for index in inspector.get_indexes("creative_runs")
    )


def _has_unverified_product_images(connection: Connection) -> bool:
    assets = Table("project_assets", MetaData(), autoload_with=connection)
    rows = connection.execute(
        select(assets.c["metadata"]).where(assets.c.asset_type == "product_image")
    ).scalars()
    return any(
        not isinstance(metadata, dict) or metadata.get("verified") is not True
        for metadata in rows
    )
