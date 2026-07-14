from sqlalchemy.engine import Engine
from sqlmodel import create_engine

from app.core.config import ensure_local_var_dir, get_settings


def create_app_engine(database_url: str | None = None) -> Engine:
    """创建业务数据库引擎。"""

    ensure_local_var_dir()
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)
