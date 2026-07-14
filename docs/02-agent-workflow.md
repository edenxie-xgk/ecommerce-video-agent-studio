# Agent 工作流

日常开发优先阅读 [Project Brief](00-project-brief.md)。本文件只记录 LangGraph 工作流节点、Agent 职责、Prompt 编辑检测、状态和失败策略；Service/Provider 接口见架构文档。

## 1. 总体原则

跨文档 Agent/Service/schema 原则见 [Hermes Engineering](HERMES_ENGINEERING.md)。本节只补充工作流专属约束。

工作流形态：

- 第一版用 LangGraph StateGraph 编排固定 Agent 工作流，不做全局自由聊天式多 Agent。
- LangGraph 负责阶段流转、人工确认暂停、恢复和重跑入口。
- 第一版只允许 Review & Cost Gate 使用局部多 Agent，且必须是固定 reviewer + aggregator 模式。
- Agent 可以推荐镜头生成方式，但不能替用户完全自动决定。用户必须能确认和修改。

## 2. LangGraph 节点

第一版固定节点：

```text
product_understanding
confirm_product_understanding
creative_script
confirm_script
storyboard_prompt
prompt_review_edit
prompt_check
confirm_storyboard_prompt
review_cost_gate
confirm_generation_task
create_generation_task
export_project
```

确认节点必须暂停，等待前端用户操作后再继续。真实生成任务只能在 `confirm_generation_task` 之后创建。

## 3. Product Understanding Agent

职责：

- 读取商品资料。
- 分析 1-5 张商品图片。
- 校对商品名称、卖点和商品图片是否一致。
- 总结商品外观、颜色、材质、使用场景和图片质量。
- 生成用户可确认的商品理解结果。

输出：

- 商品确认名称。
- 商品视觉摘要。
- 图片可用性评分。
- 商品可能卖点。
- 需要用户补充的问题。

必须人工确认。

## 4. Creative Script Agent

职责：

- 根据商品理解结果、平台和风格生成短视频脚本。
- 默认生成 3 个创意变体。
- 输出分块脚本，不输出一整段难编辑文本。

输出结构：

- 创意方向。
- 开头钩子。
- 痛点。
- 卖点。
- 使用场景。
- 转化语。

可重写动作：

- 更搞笑。
- 更高级。
- 更短。
- 更强转化。
- 更像小红书。
- 更像抖音。

必须人工确认。

## 5. Storyboard Prompt Agent

职责：

- 把确认后的脚本拆成 3 个镜头。
- 生成普通模式 Prompt。
- 推荐每个镜头的生成方式。
- 标记场景意图、商品保真风险和动作复杂度。

每个镜头输出：

- 镜头编号。
- 时长。
- 画面描述。
- 动作描述。
- 商品露出方式。
- 字幕文案。
- 视频生成 Prompt。
- 负向约束。
- 推荐生成方式和推荐理由。
- 场景意图、商品保真风险、动作复杂度。

必须人工确认。

## 6. Prompt Review & Edit / Prompt Check

Storyboard Prompt Agent 生成 Prompt 后，必须先给用户查看和修改。用户修改后不能直接进入生成，必须经过 Prompt Check。

Prompt Check 检查：

- Prompt 是否为空或过短。
- 是否缺少商品露出。
- 是否包含禁用词或明显夸大表达。
- 是否偏离原始 shot intent。
- 是否和当前 generation_mode 冲突。
- 高保真商品展示是否误用 text_to_video。
- 动作复杂度是否明显过高。

输出：

- check_status：passed / warning / blocked。
- issues。
- intent_alignment_score。
- intent_shift_detected。
- recommended_generation_mode。
- product_fidelity_risk。
- motion_complexity。
- requires_user_confirmation。

如果 blocked，返回用户继续修改。warning 可以由用户确认风险后继续。

## 7. Review & Cost Gate

这是第一版唯一的局部多 Agent 节点，用于真实生成前的审核和成本门禁。它不是自由讨论，也不决定是否直接执行生成；最终放行必须经过用户确认和 Service 校验。

子 Agent：

| Agent | 职责 |
| --- | --- |
| Compliance Reviewer | 禁用词、类目风险、夸大宣传、平台风险 |
| Product Fidelity Reviewer | 商品前后一致、Logo/包装文字、文生视频误用风险 |
| Prompt Quality Reviewer | Prompt 是否清晰、负向约束是否充分、镜头目标是否可生成 |
| Cost Reviewer | 是否建议真实生成、建议 preset、预算和重试风险 |
| Review Aggregator | 汇总 reviewer 结果，输出单一结构化 ReviewRun |

职责：

- 检查脚本、分镜、Prompt 是否违背后台规则。
- 检查禁用词、类目风险和夸大宣传。
- 检查商品前后不一致。
- 检查镜头是否缺少商品露出。
- 检查字幕是否可能遮挡商品。
- 检查生成方式是否明显不适配镜头目标。
- 检查文生视频是否被误用于高保真商品展示。
- 检查是否应该先使用 dev_check 或 shot_preview。
- 检查完整真实生成是否超出预算或风险过高。

输出：

- 审核状态。
- 风险等级。
- 风险项。
- 修改建议。
- 自动修订草稿。
- 推荐动作：放行、修改后放行、先预览、切换生成方式、人工处理。
- 推荐 generation_preset。
- 是否允许进入真实生成确认。

不自动应用修改，用户确认后应用。

## 8. 工作流状态

```text
draft
input_ready
understanding_running
understanding_review
script_running
script_review
storyboard_prompt_running
prompt_editing
prompt_checking
prompt_check_failed
storyboard_prompt_review
review_running
review_failed
generation_waiting_confirmation
generation_running
generation_partially_failed
generation_completed
video_downloading
composing
exported
```

## 9. 失败策略

视频镜头生成失败：

```text
单镜头最多自动重试 N 次
-> 仍失败则允许改写 Prompt 后重试
-> 仍失败则跳过镜头、切换生成方式或标记人工处理
```

Agent 失败：

```text
记录错误
-> 允许重跑当前 Agent
-> 允许切换模型后重跑
-> 不自动清空之前版本
```
