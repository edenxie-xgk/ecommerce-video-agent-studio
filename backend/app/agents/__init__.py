"""封装 LangGraph 创意 Agent 的状态、节点、运行时和基础设施实现。

包内分层约定：``state`` 定义跨节点数据，``nodes`` 实现业务步骤，``modeling`` 隔离
外部模型协议，``graph`` 负责编排，``planner`` 则向应用层提供稳定入口。
"""
