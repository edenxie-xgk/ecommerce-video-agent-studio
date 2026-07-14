from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlmodel import Session

from app.application.creative_agent import CreativeAgentPort
from app.application.creative_runs import CreativeRunService
from app.db.migrations import upgrade_business_database
from app.db.session import create_app_engine

engine = create_app_engine()
_database_ready = False


def ensure_database_ready() -> None:
    """通过 Alembic 迁移初始化业务数据库。"""

    global _database_ready
    if _database_ready:
        return

    upgrade_business_database()
    _database_ready = True


def get_db() -> Iterator[Session]:
    """Provide a database session to API routes."""

    ensure_database_ready()
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


def get_creative_agent(request: Request) -> CreativeAgentPort:
    """从应用启动装配结果中读取公开 Agent 端口。"""

    return cast(CreativeAgentPort, request.app.state.creative_agent)


CreativeAgentDep = Annotated[CreativeAgentPort, Depends(get_creative_agent)]


def get_creative_run_service(
    session: SessionDep,
    agent: CreativeAgentDep,
) -> CreativeRunService:
    """为 API 请求创建只依赖应用契约的创意运行服务。"""

    return CreativeRunService(session, agent)


CreativeRunServiceDep = Annotated[
    CreativeRunService,
    Depends(get_creative_run_service),
]
