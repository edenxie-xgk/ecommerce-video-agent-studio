"""构建应用进程共享的 Provider、SQLite checkpoint 和创意图实例。

FastAPI 依赖注入通过本模块取得同一个 ``CreativeAgentPort``。缓存的目标是图和
SQLite 连接，而不是一次具体的业务运行；每次运行仍使用独立 execution_id。
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config import ensure_local_var_dir, get_settings
from app.agents.planner import CreativePlanner
from app.agents.state import build_checkpoint_serializer
from app.application.creative_agent import CreativeAgentPort


@lru_cache
def get_creative_agent() -> CreativeAgentPort:
    """构建进程内共享、带 SQLite checkpoint 的 Agent 端口实现。

    ``lru_cache`` 确保同一进程只初始化一次连接和已编译图，减少连接创建和建表开销。
    """

    # 路径可能首次启动时尚不存在，先由配置层创建应用本地数据目录。
    ensure_local_var_dir()
    # Settings 是环境变量与默认值的唯一来源，避免在 Agent 层硬编码路径。
    settings = get_settings()
    # 连接需要跨 FastAPI 工作线程复用，因此关闭 SQLite 的同线程限制。
    connection = sqlite3.connect(
        settings.langgraph_checkpoint_path,
        check_same_thread=False,
    )
    # 显式注入自定义序列化器，确保 Pydantic 状态模型能完整往返 SQLite。
    checkpointer = SqliteSaver(connection, serde=build_checkpoint_serializer())
    # setup 由官方 checkpointer 创建自身表结构。
    checkpointer.setup()
    # Planner 只接收 checkpoint；节点所需模型会在执行时从配置模型获取。
    return CreativePlanner(
        checkpointer=checkpointer,
    )

