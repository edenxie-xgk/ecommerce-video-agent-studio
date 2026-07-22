from datetime import datetime
from typing import Literal

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.project import utc_now


WorkflowRunStatus = Literal["running", "waiting_confirmation", "completed", "failed", "cancelled"]
WorkflowNodeStatus = Literal["pending", "running", "waiting_confirmation", "succeeded", "failed", "skipped"]


class WorkflowRun(SQLModel, table=True):
    """一次完整 LangGraph 工作流运行，是页面恢复和节点追踪的事实来源。"""

    __tablename__ = "workflow_runs"

    id: int | None = Field(default=None, primary_key=True, description="工作流运行 ID。")
    project_id: int = Field(
        foreign_key="video_projects.id",
        index=True,
        description="所属项目 ID。",
    )
    checkpoint_thread_id: str = Field(
        index=True,
        unique=True,
        description="LangGraph checkpoint 使用的稳定线程 ID。",
    )
    status: str = Field(default="running", description="工作流运行状态。")
    current_node: str | None = Field(
        default=None,
        description="当前执行、刚完成或等待用户确认的工作流节点。",
    )
    pending_confirmation: bool = Field(
        default=False,
        description="是否正在等待用户确认后继续工作流。",
    )
    workflow_status: str = Field(
        default="draft",
        description="面向业务页面恢复的工作流阶段状态。",
    )
    prompt_revision: int = Field(
        default=0,
        nullable=False,
        description="分镜 Prompt 编辑的乐观锁版本；每次成功复检递增。",
    )
    started_at: datetime = Field(default_factory=utc_now, description="工作流开始时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="工作流更新时间。")
    completed_at: datetime | None = Field(default=None, description="当前自动运行段完成时间。")
    error_message: str | None = Field(default=None, description="不可恢复错误信息。")
    run_metadata: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON),
        description="工作流输入快照、最终决策索引和兼容页面展示的轻量元数据。",
    )


class WorkflowNodeRun(SQLModel, table=True):
    """记录工作流中一个节点的执行结果和主要输出引用。"""

    __tablename__ = "workflow_node_runs"

    id: int | None = Field(default=None, primary_key=True, description="节点运行 ID。")
    workflow_run_id: int = Field(
        foreign_key="workflow_runs.id",
        index=True,
        description="所属工作流运行 ID。",
    )
    project_id: int = Field(
        foreign_key="video_projects.id",
        index=True,
        description="所属项目 ID。",
    )
    node_name: str = Field(description="工作流节点名称。")
    status: str = Field(default="pending", description="节点运行状态。")
    agent_run_id: int | None = Field(default=None, description="节点产生的 AgentRun ID。")
    review_run_id: int | None = Field(default=None, description="节点产生的 ReviewRun ID。")
    generation_task_id: int | None = Field(default=None, description="节点创建的 GenerationTask ID。")
    output_ref_type: str | None = Field(
        default=None,
        description="节点主要输出对象类型。",
    )
    output_ref_id: int | None = Field(default=None, description="节点主要输出对象 ID。")
    started_at: datetime = Field(default_factory=utc_now, description="节点开始时间。")
    finished_at: datetime | None = Field(default=None, description="节点完成时间。")
    retry_count: int = Field(default=0, description="节点重试次数。")
    error_message: str | None = Field(default=None, description="节点失败原因。")
    node_metadata: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON),
        description="节点补充元数据。",
    )


class AgentRun(SQLModel, table=True):
    """记录一次 Agent 节点调用的输入、输出和模型运行元数据。"""

    __tablename__ = "agent_runs"

    id: int | None = Field(default=None, primary_key=True, description="Agent 运行 ID。")
    project_id: int = Field(
        foreign_key="video_projects.id",
        index=True,
        description="所属项目 ID。",
    )
    workflow_run_id: int = Field(
        foreign_key="workflow_runs.id",
        index=True,
        description="所属工作流运行 ID。",
    )
    workflow_node_run_id: int | None = Field(
        default=None,
        foreign_key="workflow_node_runs.id",
        description="所属节点运行 ID。",
    )
    agent_type: str = Field(description="Agent 类型或节点职责。")
    status: str = Field(default="succeeded", description="Agent 运行状态。")
    provider_key: str | None = Field(default=None, description="实际使用的模型 Provider 标识。")
    model_key: str | None = Field(default=None, description="实际使用的模型标识。")
    prompt_version: str | None = Field(default=None, description="使用的 Prompt 版本标识。")
    input_payload: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="传入 Agent 的业务输入快照。",
    )
    output_payload: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Agent 输出的结构化结果。",
    )
    token_usage: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="模型 Token 使用情况。",
    )
    latency_ms: int | None = Field(default=None, description="Agent 执行耗时，单位毫秒。")
    estimated_cost: float | None = Field(default=None, description="本次模型调用预估成本。")
    error_message: str | None = Field(default=None, description="Agent 失败原因。")
    created_at: datetime = Field(default_factory=utc_now, description="Agent 运行创建时间。")


class CreativeRun(SQLModel, table=True):
    """旧版单表创意运行记录；新主流程改用 WorkflowRun 和 WorkflowNodeRun。"""

    __tablename__ = "creative_runs"

    id: int | None = Field(default=None, primary_key=True, description="创意运行 ID。")
    project_id: int = Field(
        foreign_key="video_projects.id",
        index=True,
        description="所属项目 ID。",
    )
    thread_id: str = Field(
        index=True,
        unique=True,
        description="对应 LangGraph checkpoint 的稳定线程 ID。",
    )
    status: str = Field(default="running", description="运行状态。")
    action: str | None = Field(default=None, description="Agent 当前建议用户执行的动作。")
    confidence: float | None = Field(default=None, description="当前决策置信度。")
    provider_key: str = Field(default="local", description="实际生成方案的 Provider 标识。")
    model_key: str | None = Field(default=None, description="实际生成方案的模型标识。")
    revision_count: int = Field(default=0, description="质量评估后自动修订次数。")
    input_payload: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="创建运行时保存的业务输入快照。",
    )
    output_payload: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="带 Schema 版本且通过 Pydantic 校验的最终决策结果。",
    )
    started_at: datetime = Field(default_factory=utc_now, description="运行开始时间。")
    completed_at: datetime | None = Field(default=None, description="运行完成时间。")
    error_message: str | None = Field(default=None, description="不可恢复错误信息。")
