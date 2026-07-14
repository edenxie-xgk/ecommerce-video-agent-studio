# 开发路线图

日常开发优先阅读 [Project Brief](00-project-brief.md)。本文件只记录阶段安排。

## 阶段 0：工程骨架和文档

目标：

- 项目目录。
- 核心文档。
- MVP 边界、LangGraph 架构、数据模型、路线图。

验收：

- 文档能支撑开始写代码。
- 不再反复丢失项目目标。

## 阶段 1：配置后台和基础数据

目标：

- SQLModel / Alembic 基础模型和迁移。
- SQLAdmin 配置后台。
- 商品类别、卖点、适用人群、风格预设。
- 禁用词/风险规则。
- 模型供应商、视频供应商、成本规则、视频规格档位配置。
- 配置导入导出 JSON。

## 阶段 2：项目创建和商品输入

目标：

- FastAPI API 和 openapi-typescript / openapi-fetch 前端类型链路。
- Vue + Naive UI + TanStack Query 基础创作台。
- 项目列表和创建项目。
- 商品资料表单。
- 商品图、Logo、背景音乐上传。

验收：

- 可以保存 VideoProject、ProductBrief、ProjectAsset。

## 阶段 3：Agent 工作流前半段

目标：

- LangGraph StateGraph 基础节点。
- Product Understanding Agent node。
- Creative Script Agent node。
- 3 个创意变体。
- 脚本块编辑和 AgentRun 日志。

验收：

- 可以从商品资料生成商品理解和脚本，并支持确认、编辑、重跑。

## 阶段 4：分镜、Prompt 和审核

目标：

- Storyboard Prompt Agent node。
- MVP 镜头分镜。
- Prompt Review & Edit 节点。
- Prompt Check 节点。
- 镜头生成方式建议和用户确认。
- LangGraph Review & Cost Gate 节点。
- Compliance / Product Fidelity / Prompt Quality / Cost reviewer。
- Review Aggregator 输出单一 ReviewRun。

验收：

- 可以生成镜头和 Prompt。
- 用户可以查看、修改 Prompt。
- 修改后 Prompt 能检测安全、意图偏移、商品保真和生成方式冲突。
- 可以生成 Review & Cost Gate 结果和 GenerationTask 草稿。
- 真实生成前能给出风险、推荐 preset 和是否建议先预览。

## 阶段 5：Mock 视频生成和工程导出

目标：

- MockProvider。
- MVP 两类生成模式的 mock 能力。
- GenerationTask 状态流转。
- 失败重试逻辑。
- 工程 JSON、脚本 Markdown、Prompt 列表导出。
- 成本统计。

验收：

- 不调用真实视频 API 也能跑完整流程。

## 阶段 6：真实视频供应商接入

目标：

- 实现 VideoProviderAdapter。
- 接入第一真实供应商。
- 按 GenerationSpec 校验能力、预算和确认要求。
- 生成、轮询、下载、转存视频片段。

验收：

- 可以真实生成视频片段。
- 成本、耗时、供应商任务 ID、模型、分辨率、失败原因被记录。

## 阶段 7：FFmpeg 合成和导出 MP4

目标：

- 粗略字幕时间轴。
- 字幕样式。
- Logo 水印。
- 背景音乐合成。
- MVP MP4 导出。

验收：

- 可以导出和预览完整商品短视频。

## 阶段 8：第一梯队增强

目标：

- 精准字幕对齐。
- 自动音乐推荐。
- 封面生成。
- 竞品分析。
- 视频编辑模型用于局部修复和风格统一。

暂缓事项以 [Project Brief](00-project-brief.md) 的 MVP 边界为准。
