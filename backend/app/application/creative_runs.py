"""编排创意运行用例，并显式映射数据库记录与 Agent 输入。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlmodel import Session, select

from app.application.creative_agent import (
    CreativeAgentPort,
    CreativeAgentResult,
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeDecisionBundle,
    CreativeProjectInput,
    CreativeRunInput,
    DecisionAction,
)
from app.models.creative import AgentRun, CreativeRun, WorkflowNodeRun, WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject, utc_now


PRODUCT_UNDERSTANDING_NODE = "product_understanding"  # 商品理解节点。
CREATIVE_SCRIPT_NODE = "creative_script"  # 创意脚本节点。
STORYBOARD_PROMPT_NODE = "storyboard_prompt"  # 分镜 Prompt 节点。
PROMPT_CHECK_NODE = "prompt_check"  # Prompt 检测节点。
REVIEW_COST_GATE_NODE = "review_cost_gate"  # 审核和成本门禁节点。
CONFIRM_GENERATION_TASK_NODE = "confirm_generation_task"  # 真实生成前的用户确认节点。

# Agent 运行投影到业务数据库后的页面状态。
RunStatus = Literal[
    "ready_for_review",  # 方案通过质量门禁，等待人工审核或采用。
    "quality_blocked",  # 方案未通过质量门禁，需要处理质量问题。
]

# CreativeRun.output_payload 的信封版本；结构变更时递增并做兼容读取。
DECISION_PAYLOAD_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreativeRunProjection:
    """描述 Agent 结果应映射到的唯一业务状态和动作。"""

    status: RunStatus
    workflow_status: str
    current_node: str
    pending_confirmation: bool
    action: DecisionAction


def project_run_result(result: CreativeAgentResult) -> CreativeRunProjection:
    """根据最终质量结果计算业务状态和下一步动作。"""

    if result.bundle.evaluation.passed:
        return CreativeRunProjection(
            status="ready_for_review",
            workflow_status="generation_waiting_confirmation",
            current_node=CONFIRM_GENERATION_TASK_NODE,
            pending_confirmation=True,
            action="review_plan",
        )
    return CreativeRunProjection(
        status="quality_blocked",
        workflow_status="review_failed",
        current_node=REVIEW_COST_GATE_NODE,
        pending_confirmation=True,
        action="resolve_quality_issues",
    )


def serialize_decision_result(bundle: CreativeDecisionBundle) -> dict[str, object]:
    """把当前决策写入带版本的持久化信封，供未来显式升级。"""

    return {
        "schema_version": DECISION_PAYLOAD_SCHEMA_VERSION,
        "decision": bundle.model_dump(mode="json"),
    }


class CreativeRunService:
    """实现创意工作流用例，并把 Agent 结果投影为工作流记录。"""

    def __init__(
        self,
        session: Session,
        agent: CreativeAgentPort,
    ) -> None:
        """注入数据库会话和应用层 Agent 端口。"""

        self._session = session
        self._agent = agent

    def generate(self, *, project_id: int, campaign_goal: str) -> WorkflowRun:
        """加载业务数据、创建工作流运行并执行当前自动节点段。"""

        project, brief, assets = self._load_project_context(project_id)
        self._validate_ready_for_agent(brief=brief, assets=assets)
        execution_id = uuid4().hex
        input_payload = {
            "campaign_goal": campaign_goal,
            "target_platform": project.target_platform,
            "product_brief_id": brief.id if brief else None,
            "product_asset_ids": [asset.id for asset in assets],
        }
        run = WorkflowRun(
            project_id=project_id,
            checkpoint_thread_id=execution_id,
            status="running",
            current_node=PRODUCT_UNDERSTANDING_NODE,
            pending_confirmation=False,
            workflow_status="understanding_running",
            run_metadata={"input": input_payload, "campaign_goal": campaign_goal},
        )
        self._session.add(run)
        self._session.commit()
        self._session.refresh(run)

        try:
            result = self._agent.run(
                self._to_run_input(
                    project=project,
                    brief=brief,
                    assets=assets,
                    campaign_goal=campaign_goal,
                ),
                execution_id=execution_id,
            )
            return self._apply_result(run, project, result)
        except Exception as exc:
            self._mark_failed(run, project, exc)
            raise

    def list_for_project(self, project_id: int) -> list[WorkflowRun]:
        """按时间倒序返回项目的历史工作流运行。"""

        return list(
            self._session.exec(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project_id)
                .order_by(WorkflowRun.id.desc())
            ).all()
        )

    @staticmethod
    def parse_result(run: WorkflowRun | CreativeRun) -> CreativeDecisionBundle | None:
        """把数据库 JSON 重新校验为公开决策契约。"""

        payload = CreativeRunService._stored_decision_payload(run)
        if payload is None:
            return None
        if "schema_version" in payload:
            if payload.get("schema_version") != DECISION_PAYLOAD_SCHEMA_VERSION:
                logger.warning(
                    "Unsupported creative decision payload version for run %s: %r",
                    run.id,
                    payload.get("schema_version"),
                )
                return None
            decision_payload = payload.get("decision")
            if not isinstance(decision_payload, dict):
                logger.warning("Creative decision payload is malformed for run %s", run.id)
                return None
        else:
            # 版本字段引入前，output_payload 直接保存决策对象。
            decision_payload = payload

        try:
            return CreativeDecisionBundle.model_validate(decision_payload)
        except ValidationError:
            logger.warning(
                "Creative decision payload is incompatible for run %s",
                run.id,
                exc_info=True,
            )
            return None

    def _load_project_context(
        self,
        project_id: int,
    ) -> tuple[VideoProject, ProductBrief | None, list[ProjectAsset]]:
        """从数据库读取构造 Agent 输入所需的唯一事实来源。"""

        project = self._session.get(VideoProject, project_id)
        if project is None:
            raise KeyError(f"找不到项目：{project_id}")

        brief = self._session.exec(
            select(ProductBrief).where(ProductBrief.project_id == project_id)
        ).first()
        assets = list(
            self._session.exec(
                select(ProjectAsset)
                .where(ProjectAsset.project_id == project_id)
                .where(ProjectAsset.asset_type == "product_image")
                .order_by(ProjectAsset.id)
            ).all()
        )
        return project, brief, assets

    @staticmethod
    def _validate_ready_for_agent(
        *,
        brief: ProductBrief | None,
        assets: list[ProjectAsset],
    ) -> None:
        """在创建 CreativeRun 前校验当前版本的硬门槛输入。"""

        missing: list[str] = []
        product_name = (brief.product_name if brief else "").strip()
        if not product_name:
            missing.append("商品名称")
        if not assets:
            missing.append("至少一张已验证商品图片")
        if missing:
            raise ValueError("资料未达到启动硬门槛，Agent 未创建运行。请先补齐：" + "、".join(missing))

    @staticmethod
    def _to_run_input(
        *,
        project: VideoProject,
        brief: ProductBrief | None,
        assets: list[ProjectAsset],
        campaign_goal: str,
    ) -> CreativeRunInput:
        """把数据库记录转换为不依赖 ORM 的新运行输入。"""

        return CreativeRunInput(
            project=CreativeRunService._to_project_input(project),
            brief=CreativeRunService._to_brief_input(brief),
            assets=[CreativeRunService._to_asset_input(asset) for asset in assets],
            campaign_goal=campaign_goal,
        )

    @staticmethod
    def _to_project_input(project: VideoProject) -> CreativeProjectInput:
        """明确列出允许进入 Agent 的项目字段。"""

        return CreativeProjectInput(
            id=project.id,
            title=project.title,
            target_platform=project.target_platform,
            language=project.language,
            aspect_ratio=project.aspect_ratio,
            duration_seconds=project.duration_seconds,
            status=project.status,
        )

    @staticmethod
    def _to_brief_input(brief: ProductBrief | None) -> CreativeBriefInput | None:
        """明确列出允许进入 Agent 的商品资料字段。"""

        if brief is None:
            return None
        return CreativeBriefInput(
            id=brief.id,
            project_id=brief.project_id,
            product_name=brief.product_name,
            selling_points_text=brief.selling_points_text,
            target_audience_text=brief.target_audience_text,
            brand_tone=brief.brand_tone,
            forbidden_words_text=brief.forbidden_words_text,
        )

    @staticmethod
    def _to_asset_input(asset: ProjectAsset) -> CreativeAssetInput:
        """明确列出允许进入 Agent 的素材引用字段。"""

        return CreativeAssetInput(
            id=asset.id,
            project_id=asset.project_id,
            asset_type=asset.asset_type,
            storage_key=asset.storage_key,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            asset_metadata=asset.asset_metadata,
        )

    def _apply_result(
        self,
        run: WorkflowRun,
        project: VideoProject,
        result: CreativeAgentResult,
    ) -> WorkflowRun:
        """把 Agent 结果投影回工作流运行、节点运行和项目状态。"""

        projection = project_run_result(result)
        bundle_payload = result.bundle.model_dump(mode="json")
        bundle_payload["action"] = projection.action
        bundle = CreativeDecisionBundle.model_validate(bundle_payload)
        decision_payload = serialize_decision_result(bundle)

        self._record_agent_node(
            run=run,
            node_name=PRODUCT_UNDERSTANDING_NODE,
            provider_key="local",
            model_key=None,
            input_payload=CreativeRunService._run_input_metadata(run),
            output_payload=bundle.analysis.model_dump(mode="json"),
        )
        self._record_agent_node(
            run=run,
            node_name=CREATIVE_SCRIPT_NODE,
            provider_key=result.provider_key,
            model_key=result.model_key,
            input_payload={"analysis": bundle.analysis.model_dump(mode="json")},
            output_payload={
                "decision_reason": bundle.decision_reason,
                "confidence": bundle.confidence,
                "concepts": [concept.model_dump(mode="json") for concept in bundle.concepts],
            },
        )
        self._record_agent_node(
            run=run,
            node_name=STORYBOARD_PROMPT_NODE,
            provider_key="local",
            model_key=None,
            input_payload={"concept_count": len(bundle.concepts)},
            output_payload={
                "storyboards": [
                    {
                        "concept_key": concept.concept_key,
                        "shots": [shot.model_dump(mode="json") for shot in concept.shots],
                    }
                    for concept in bundle.concepts
                ],
            },
        )
        self._record_agent_node(
            run=run,
            node_name=PROMPT_CHECK_NODE,
            provider_key="local",
            model_key=None,
            input_payload={"concept_count": len(bundle.concepts)},
            output_payload=bundle.evaluation.model_dump(mode="json"),
        )
        self._record_agent_node(
            run=run,
            node_name=REVIEW_COST_GATE_NODE,
            provider_key="local",
            model_key=None,
            input_payload={"concept_count": len(bundle.concepts)},
            output_payload=decision_payload,
        )

        run.status = "waiting_confirmation"
        run.current_node = projection.current_node
        run.pending_confirmation = projection.pending_confirmation
        run.workflow_status = projection.workflow_status
        run.error_message = None
        run.updated_at = utc_now()
        run.completed_at = utc_now()
        run.run_metadata = {
            **(run.run_metadata or {}),
            "public_status": projection.status,
            "action": projection.action,
            "confidence": bundle.confidence,
            "provider_key": result.provider_key,
            "model_key": result.model_key,
            "revision_count": bundle.revision_count,
            "decision_payload": decision_payload,
        }

        project.status = projection.status
        project.updated_at = utc_now()
        self._session.add(project)
        self._session.add(run)
        self._session.commit()
        self._session.refresh(run)
        return run

    def _mark_failed(
        self,
        run: WorkflowRun,
        project: VideoProject,
        error: Exception,
    ) -> None:
        """清理旧决策并同步工作流和项目的不可恢复失败状态。"""

        run.status = "failed"
        run.workflow_status = "review_failed"
        run.pending_confirmation = False
        stale_decision_keys = {
            "action",
            "confidence",
            "decision_payload",
            "model_key",
            "provider_key",
            "public_status",
            "revision_count",
        }
        run.run_metadata = {
            key: value
            for key, value in (run.run_metadata or {}).items()
            if key not in stale_decision_keys
        }
        run.error_message = str(error)
        run.updated_at = utc_now()
        run.completed_at = utc_now()
        project.status = "failed"
        project.updated_at = utc_now()
        self._session.add(project)
        self._session.add(run)
        self._session.commit()

    def _record_agent_node(
        self,
        *,
        run: WorkflowRun,
        node_name: str,
        provider_key: str | None,
        model_key: str | None,
        input_payload: dict[str, object],
        output_payload: dict[str, object],
    ) -> None:
        """保存一个自动节点的节点记录和对应 AgentRun。"""

        now = utc_now()
        node = WorkflowNodeRun(
            workflow_run_id=run.id or 0,
            project_id=run.project_id,
            node_name=node_name,
            status="succeeded",
            output_ref_type="agent_run",
            started_at=now,
            finished_at=now,
        )
        self._session.add(node)
        self._session.commit()
        self._session.refresh(node)

        agent_run = AgentRun(
            project_id=run.project_id,
            workflow_run_id=run.id or 0,
            workflow_node_run_id=node.id,
            agent_type=node_name,
            status="succeeded",
            provider_key=provider_key,
            model_key=model_key,
            input_payload=input_payload,
            output_payload=output_payload,
        )
        self._session.add(agent_run)
        self._session.commit()
        self._session.refresh(agent_run)

        node.agent_run_id = agent_run.id
        node.output_ref_id = agent_run.id
        self._session.add(node)
        self._session.commit()

    @staticmethod
    def _run_input_metadata(run: WorkflowRun) -> dict[str, object]:
        """读取工作流运行中的输入快照。"""

        metadata = run.run_metadata or {}
        input_payload = metadata.get("input")
        return input_payload if isinstance(input_payload, dict) else {}

    @staticmethod
    def _stored_decision_payload(run: WorkflowRun | CreativeRun) -> dict[str, object] | None:
        """兼容读取新版 WorkflowRun 或旧版 CreativeRun 的最终决策信封。"""

        if isinstance(run, WorkflowRun):
            payload = (run.run_metadata or {}).get("decision_payload")
            return payload if isinstance(payload, dict) else None
        return run.output_payload

    @staticmethod
    def public_status(run: WorkflowRun) -> str:
        """读取兼容前端展示的运行状态。"""

        status = (run.run_metadata or {}).get("public_status")
        return status if isinstance(status, str) else run.workflow_status

    @staticmethod
    def action(run: WorkflowRun) -> str | None:
        """读取 Agent 建议用户执行的下一步动作。"""

        action = (run.run_metadata or {}).get("action")
        return action if isinstance(action, str) else None

    @staticmethod
    def confidence(run: WorkflowRun) -> float | None:
        """读取最终决策置信度。"""

        confidence = (run.run_metadata or {}).get("confidence")
        return confidence if isinstance(confidence, int | float) else None

    @staticmethod
    def provider_key(run: WorkflowRun) -> str:
        """读取完成创意脚本生成的 Provider 标识。"""

        provider_key = (run.run_metadata or {}).get("provider_key")
        return provider_key if isinstance(provider_key, str) else "local"

    @staticmethod
    def model_key(run: WorkflowRun) -> str | None:
        """读取完成创意脚本生成的模型标识。"""

        model_key = (run.run_metadata or {}).get("model_key")
        return model_key if isinstance(model_key, str) else None

    @staticmethod
    def revision_count(run: WorkflowRun) -> int:
        """读取质量门禁自动修订次数。"""

        revision_count = (run.run_metadata or {}).get("revision_count")
        return revision_count if isinstance(revision_count, int) else 0

    @staticmethod
    def campaign_goal(run: WorkflowRun) -> str | None:
        """读取创建运行时保存的营销目标快照。"""

        campaign_goal = (run.run_metadata or {}).get("campaign_goal")
        return campaign_goal if isinstance(campaign_goal, str) else None
