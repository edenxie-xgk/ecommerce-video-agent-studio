# 决策记录

日常开发优先阅读 [Project Brief](00-project-brief.md)。当前结论按职责维护到对应权威文档；本文件只记录决策原因、备选和未冻结事项。

## 1. 已冻结方向的原因

| 决策项 | 权威位置 | 原因和备选 |
| --- | --- | --- |
| Agent 工作流框架 | Project Brief / Agent 工作流 / 技术架构 | 选择 LangGraph StateGraph 做主编排，便于阅读、维护、扩展和 human-in-the-loop；Pydantic AI 不进 MVP 主路线。 |
| 结构化输出 | Hermes / Agent 工作流 / 数据模型 | 使用 Pydantic schema 校验 Agent 输出和 Prompt Check 结果，避免 graph state 变成不可控文本。 |
| Prompt 编辑检测 | Agent 工作流 | Storyboard 后必须给用户查看和修改 Prompt；修改后必须检测安全、意图偏移、商品保真和生成方式冲突。 |
| 局部多 Agent | Agent 工作流 | 仅在 Review & Cost Gate 使用 reviewer + aggregator 模式，用于降低真实视频浪费和商品保真风险；不扩展成全局自由多 Agent。 |
| UI 库 | Project Brief / 技术架构 | 个人开发优先快速搭建后台和创作台；Element Plus 仅作为历史备选，不是当前路线。 |
| 前端请求状态 | Project Brief / 技术架构 | TanStack Query 管理 server state、轮询、loading/error，减少手写状态代码。 |
| 前端类型链路 | Project Brief / 技术架构 | openapi-fetch / openapi-typescript 复用 FastAPI OpenAPI schema，减少接口类型手写。 |
| 数据层 | Project Brief / 技术架构 / 数据模型 | SQLModel 减少 SQLAlchemy/Pydantic 双写；Alembic 负责迁移。 |
| 配置后台 | Project Brief / 技术架构 / 数据模型 | SQLAdmin 优先承接后台 CRUD，前台创作台保留自研。 |
| 队列 | Project Brief / 技术架构 | 任务模型简单时优先 Redis + RQ；Celery 仅作为任务复杂后的再评估对象，不是当前路线。 |
| 生成方式命名 | Project Brief / 产品范围 | 用户侧用业务语言，数据层用技术枚举，避免把模型术语直接暴露给运营用户。 |
| MockProvider | Project Brief / 技术架构 | 先跑通流程和状态机，避免开发期消耗真实视频额度。 |
| 第一真实视频供应商 | Project Brief / 技术架构 | 优先国内调用链路、成本和能力组合；保留可灵、即梦、Runway、Luma、fal、ComfyUI。 |
| 视频规格档位 | Project Brief / 数据模型 | 用开发、预览、完整成片分层控制成本，避免每次测试都生成完整视频。 |
| 文生视频边界 | Project Brief / Agent 工作流 | 文生视频适合场景动作，不适合作为高保真商品展示默认路线。 |
| video-edit | Project Brief / 技术架构 | 作为后处理预留，避免第一版主流程变重。 |

## 2. 非 MVP 主路线

- Pydantic AI：适合快速结构化 Agent，但当前选择 LangGraph 作为更清晰的主工作流编排。
- AutoGen / Microsoft Agent Framework：适合技术展示型多 Agent 协作，当前市场验证版暂不采用。
- CrewAI：适合角色协作展示，当前结构化输出和稳定交付优先级更高。
- LiteLLM / Instructor：多 LLM 供应商或结构化输出不稳定时再评估。

## 3. 未完全冻结事项

- 具体本地模型。
- 精准字幕对齐方案。
- 是否接第二个真实视频供应商。

## 4. 维护规则

新增决策时只记录原因、备选和是否影响 MVP 边界。产品/MVP 结论维护到 Project Brief；工作流、架构、数据字段和路线图结论维护到对应文档。如果两边冲突，先按 Hermes 的冲突处理流程询问用户。
