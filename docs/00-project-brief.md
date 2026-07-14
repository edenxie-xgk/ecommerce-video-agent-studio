# Project Brief

本文件是日常开发优先阅读的核心上下文。详细文档只保留领域细节；协作确认、冲突处理和跨文档工程约束以 [Hermes Engineering](HERMES_ENGINEERING.md) 为准。

## 1. 定位

`Ecommerce Video Agent Studio` 是一个面向电商商品短视频素材的 AIGC 工作流工具，不是通用视频生成器。

第一版目标：把商品资料和 1-5 张商品图，转成可审核、可生成、可导出的短视频素材方案：

- 3 个创意方向。
- 中文脚本。
- 3 镜头分镜。
- 视频生成 Prompt。
- 用户查看、编辑和确认 Prompt。
- 修改后 Prompt 检测记录。
- 镜头生成方式建议。
- Review & Cost Gate 审核记录。
- 生成任务和成本记录。
- 9:16 MP4 或工程导出。

## 2. MVP 边界

第一版：

- 平台：抖音、小红书。
- 语言：中文。
- 视频比例：9:16。
- 完整成片：默认 15 秒，3 个镜头，每镜头约 5 秒。
- 创意变体：痛点型、种草型、促销型。
- 使用方式：个人开发、演示、小范围试单验证。

第一版不做：

- 多用户、团队协作、支付订阅。
- 自动发布和投放数据回流。
- 淘宝链接、网页路径或本地路径解析商品资料。
- 多供应商智能调度。
- 自动选择最佳视频模型。
- 复杂时间线编辑器。
- 稳定真人角色、视频 LoRA。
- 30 秒或更长视频。
- 把 video-edit 作为默认必经步骤。

## 3. 生成方式

用户可见名称使用业务语言：

| 用户可见名称 | 底层能力 | 默认用途 |
| --- | --- | --- |
| 场景动作 | text_to_video | 人物、使用演示、生活场景、动作镜头、痛点开场、情绪氛围 |
| 商品展示 | image_to_video | 商品特写、包装展示、主视觉、封面动态化 |

规则：

- 用户可手动修改每个镜头的生成方式。
- 系统只做简单默认推荐，不做复杂自动路由。
- MockProvider 是工程打底，不是用户可见的第三种生成方式。
- 文生视频不作为商品包装、Logo、瓶身文字或严格商品结构展示的首选方式。
- 商品保真风险高时，应提示用户确认，或建议切换到商品展示。

## 4. 视频规格

视频规格必须来自 `GenerationSpec` 或后台配置，不能在业务代码里写死。

| preset | 秒数 | 默认分辨率 | 用途 |
| --- | ---: | --- | --- |
| dev_check | 3 | 720P | 工程验证，测试 API、轮询、下载、保存 |
| shot_preview | 5 | 720P | 单镜头预览，调 Prompt 和判断镜头质量 |
| sequence_preview | 10 | 720P | 可选半成片预览，不进入默认主流程 |
| full_video | 15 | 720P，必要时 1080P | 完整成片、演示、试单或交付候选 |

完整 15 秒真实生成前必须展示预计成本并要求人工确认。

## 5. Provider 策略

第一阶段：

- MockProvider 跑通完整流程。
- Aliyun HappyHorse 作为第一真实视频供应商。

HappyHorse 能力映射：

- `text_to_video` -> `happyhorse-1.1-t2v`
- `image_to_video` -> `happyhorse-1.1-i2v`
- `video_edit` -> `happyhorse-1.0-video-edit`，仅作为后处理预留

创建真实任务前必须校验：

- duration_seconds。
- resolution。
- aspect_ratio。
- generation_mode。
- provider/model 支持范围。
- 项目预算和重试上限。

供应商返回的临时下载地址必须立即转存为本地资产或对象存储资产。

## 6. 核心数据字段

`GenerationTask` 和相关镜头数据至少记录：

- generation_mode。
- generation_preset。
- provider_key。
- model_key。
- scene_intent。
- product_fidelity_risk。
- motion_complexity。
- duration_seconds。
- aspect_ratio。
- resolution。
- estimated_cost / actual_cost。
- elapsed_seconds。
- retry_count。
- failure_code / error_message。
- output_asset_id。

## 7. 工作流

LangGraph StateGraph + 少量专业 Agent 节点 + 人工确认门禁。主路径是：

```text
商品输入 -> 商品理解 -> 脚本 -> 分镜和 Prompt -> Prompt Check
-> Review & Cost Gate -> 生成任务确认 -> Mock/真实生成 -> 合成导出
```

精确节点、Agent 职责、Prompt Check、Review & Cost Gate 和失败策略以 [Agent 工作流](02-agent-workflow.md) 为准。

## 8. 技术栈

- 前端：Vue 3 + Vite + Pinia + Naive UI + TanStack Query + openapi-fetch/openapi-typescript。
- 后端：FastAPI + LangGraph + Pydantic schema + SQLModel + Alembic + SQLAdmin。
- 数据库：PostgreSQL。
- 队列：Redis + RQ，配 rq-dashboard 观察任务。
- 媒体处理：FFmpeg。
- LLM：LangGraph Agent node + OpenAI-compatible provider abstraction；Ollama-compatible 不进第一版主路线。
- 视频：VideoProvider abstraction，先 MockProvider，再 AliyunHappyHorseProvider。
- 开发工具：uv、ruff、pytest、pydantic-settings、httpx、tenacity。

第一版采用 LangGraph 做主工作流编排，但不做自由多 Agent 对话、动态工具循环或复杂反思。Pydantic AI、AutoGen、Microsoft Agent Framework、CrewAI 不进 MVP 主路线。

## 9. 成本和稳定性

默认成本策略：

- 日常开发只用 MockProvider。
- 真实工程验证用 3 秒 720P。
- 镜头测试用 5 秒 720P。
- 完整 15 秒只用于演示、试单或交付候选。
- 单镜头必须有重试上限。
- 单项目必须有预算上限。

稳定性判断：

- 工程流程可以稳定。
- AI 视频结果不能保证稳定。
- 生成失败、商品不准、文字/Logo 变形、动作不自然都必须被视为正常风险。
