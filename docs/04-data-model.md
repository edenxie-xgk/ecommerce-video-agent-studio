# 数据模型草案

日常开发优先阅读 [Project Brief](00-project-brief.md)。本文件只记录数据结构字段。

## 1. 核心对象

```text
VideoProject
  -> ProductBrief
  -> ProjectAsset
  -> WorkflowRun
  -> WorkflowNodeRun
  -> AgentRun
  -> CreativeVariant
  -> ScriptVersion
  -> StoryboardVersion
  -> Shot
  -> PromptVersion
  -> ReviewRun
  -> GenerationTask
  -> VideoClip
  -> TimelineVersion
  -> ExportArtifact
```

## 2. VideoProject

- id。
- title。
- target_platform：douyin / xiaohongshu。
- language：zh-CN。
- aspect_ratio。
- duration_seconds。
- default_generation_preset。
- default_preview_preset。
- status。
- budget_limit。
- estimated_cost_total。
- actual_cost_total。
- created_at。
- updated_at。

## 3. ProductBrief

- project_id。
- product_name。
- category_id。
- price_text。
- selling_point_ids。
- audience_ids。
- brand_tone。
- forbidden_words_text。
- confirmed_at。

## 4. ProjectAsset

- id。
- project_id。
- type：product_image / logo / music / generated_image / video_clip / export / storyboard_markdown / prompt_bundle。
- storage_key：系统保存的素材位置，不作为用户输入字段。
- mime_type。
- size_bytes。
- metadata。
- created_at。

## 5. WorkflowRun

- id。
- project_id。
- checkpoint_thread_id：LangGraph checkpoint 使用的线程标识，用于恢复同一条图执行状态。
- status：running / waiting_confirmation / completed / failed / cancelled。
- current_node：当前执行、刚执行完成或正在等待确认的工作流节点。
- pending_confirmation：是否正在等待用户人工确认。
- workflow_status：当前 Agent 工作流阶段，区别于 VideoProject.status 的项目生命周期状态。
- started_at。
- updated_at。
- completed_at。
- error_message。
- metadata。

## 6. WorkflowNodeRun

- id。
- workflow_run_id。
- project_id。
- node_name：product_understanding / confirm_product_understanding / creative_script / confirm_script / storyboard_prompt / prompt_review_edit / prompt_check / confirm_storyboard_prompt / review_cost_gate / confirm_generation_task / create_generation_task / export_project。
- status：pending / running / waiting_confirmation / succeeded / failed / skipped。
- agent_run_id：当节点由 Agent 执行时，关联具体 AgentRun。
- review_run_id：当节点产生 ReviewRun 时，关联具体 ReviewRun。
- generation_task_id：当节点创建或处理单个 GenerationTask 时，关联具体 GenerationTask。
- output_ref_type：agent_run / review_run / generation_task / script_version / storyboard_version / prompt_version / export_artifact / none。
- output_ref_id：节点主要输出对象 ID，用于恢复页面展示和下游节点读取。
- started_at。
- finished_at。
- retry_count。
- error_message。
- metadata。

## 7. AgentRun

- id。
- project_id。
- workflow_run_id。
- workflow_node_run_id。
- agent_type。
- provider。
- model。
- input_payload。
- output_payload。
- prompt_version。
- status。
- latency_ms。
- token_usage。
- estimated_cost。
- error_message。
- created_at。

## 8. CreativeVariant

- id。
- project_id。
- variant_no。
- angle：pain_point / seeding / promotion / custom。
- title。
- description。
- status。
- confirmed_at。
- source_agent_run_id。

## 9. ScriptVersion

- id。
- project_id。
- creative_variant_id。
- version_no。
- hook。
- pain_point。
- selling_points。
- scenario。
- call_to_action。
- source_agent_run_id。
- confirmed_at。

## 10. StoryboardVersion

- id。
- project_id。
- creative_variant_id。
- version_no。
- script_version_id。
- total_duration_seconds。
- shot_count。
- confirmed_at。

## 11. Shot

- id。
- storyboard_version_id。
- shot_no。
- duration_seconds。
- visual_description。
- action_description。
- product_placement。
- subtitle_text。
- recommended_generation_mode。
- generation_mode。
- generation_mode_reason。
- generation_preset。
- resolution。
- aspect_ratio。
- scene_intent。
- product_fidelity_risk。
- motion_complexity。
- input_asset_ids。
- status。

## 12. PromptVersion

- id。
- shot_id。
- version_no。
- prompt_text。
- negative_prompt_text。
- source：agent_generated / user_edited / repaired。
- check_status：unchecked / passed / warning / blocked。
- check_payload。
- intent_alignment_score。
- intent_shift_detected。
- check_issues。
- recommended_generation_mode。
- product_fidelity_risk。
- motion_complexity。
- provider_hint。
- model_hint。
- source_agent_run_id。
- confirmed_at。

## 13. ReviewRun

- id。
- project_id。
- workflow_run_id。
- workflow_node_run_id。
- target_type：script / storyboard / prompt / full_project。
- target_id。
- review_type：single / review_cost_gate。
- status。
- risk_level。
- findings。
- suggestions。
- checklist_payload。
- reviewer_outputs。
- recommended_action：approve / revise / preview_first / switch_generation_mode / manual_required。
- recommended_generation_preset。
- should_allow_real_generation。
- budget_risk_level。
- product_fidelity_risk。
- source_agent_run_id。
- source_agent_run_ids。
- confirmed_at。

## 14. GenerationTask

- id。
- project_id。
- workflow_run_id。
- workflow_node_run_id。
- shot_id。
- prompt_version_id。
- generation_mode。
- generation_preset。
- provider_key。
- model_key。
- provider_task_id。
- status：draft / waiting_confirmation / running / succeeded / failed / skipped / manual_required。
- retry_count。
- rewritten_prompt_count。
- duration_seconds。
- aspect_ratio。
- resolution。
- scene_intent。
- product_fidelity_risk。
- motion_complexity。
- require_confirmation。
- request_payload。
- response_payload。
- output_remote_url。
- output_asset_id。
- estimated_cost。
- actual_cost。
- elapsed_seconds。
- failure_code。
- error_message。
- created_at。
- updated_at。

## 15. VideoClip

- id。
- project_id。
- shot_id。
- generation_task_id。
- storage_key：系统保存的视频片段位置，不作为用户输入字段。
- duration_seconds。
- width。
- height。
- generation_mode。
- provider_key。
- model_key。
- metadata。
- created_at。

## 16. TimelineVersion

- id。
- project_id。
- version_no。
- clip_ids。
- subtitle_tracks。
- music_asset_id。
- logo_asset_id。
- style_config。
- created_at。

## 17. ExportArtifact

- id。
- project_id。
- timeline_version_id。
- output_storage_key：系统保存的导出产物位置，不作为用户输入字段。
- engineering_json_path。
- duration_seconds。
- format。
- status。
- metadata。
- created_at。

## 18. Admin Config

配置对象：

- ProductCategory。
- SellingPointOption。
- AudienceOption。
- StylePreset。
- ForbiddenWordRule。
- CategoryRiskRule。
- ModelProviderConfig。
- AgentModelConfig。
- VideoProviderConfig。
- CostPolicyConfig。
- GenerationPresetConfig。

通用字段：

- enabled。
- sort_order。
- metadata。
- import/export JSON。

`VideoProviderConfig` 额外字段：

- provider_key。
- display_name。
- endpoint。
- region。
- supported_generation_modes。
- supported_duration_min。
- supported_duration_max。
- supported_duration_values。
- supported_resolutions。
- supported_aspect_ratios。
- price_rules。
- timeout_seconds。
- poll_interval_seconds。
- max_retry_count。

`GenerationPresetConfig` 额外字段：

- preset_key。
- display_name。
- duration_seconds。
- resolution。
- aspect_ratio。
- usage。
- require_confirmation。
- is_default。
