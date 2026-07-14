"""构建应用进程共享的 Provider、SQLite checkpoint 和创意图实例。"""

from __future__ import annotations

import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config import ensure_local_var_dir, get_settings
from app.agents.planner import CreativePlanner
from app.agents.modeling.provider import OpenAICompatibleProvider
from app.application.creative_agent import CreativeAgentPort


@lru_cache
def get_creative_agent() -> CreativeAgentPort:
    """构建进程内共享、带 SQLite checkpoint 的 Agent 端口实现。"""

    ensure_local_var_dir()
    settings = get_settings()
    # 连接需要跨 FastAPI 工作线程复用，因此关闭 SQLite 的同线程限制。
    connection = sqlite3.connect(
        settings.langgraph_checkpoint_path,
        check_same_thread=False,
    )
    checkpointer = SqliteSaver(connection)
    # setup 由官方 checkpointer 创建自身表结构。
    checkpointer.setup()
    return CreativePlanner(
        provider=OpenAICompatibleProvider(settings),
        checkpointer=checkpointer,
    )
