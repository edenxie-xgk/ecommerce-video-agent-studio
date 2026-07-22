"""定义创意计划完成分析和质量评估后的公开决策契约。"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.application.creative_plan import (
    CreativeConcept,
    CreativeDraft,
    ProductAnalysis,
    StoryboardPromptBundle,
    validate_plan_concepts,
)


# Agent 对外给出的最终动作。
DecisionAction = Literal[
    "review_plan",  # 三套方案通过质量门禁，可以进入人工审核。
    "resolve_quality_issues",  # 方案已生成但仍有质量问题，需要继续修正。
]

# 质量问题等级；warning 可带着方案继续审核，blocked 会阻断通过。
IssueSeverity = Literal[
    "warning",  # 非阻断提醒，例如时长不匹配或商品露出偏弱。
    "blocked",  # 阻断问题，例如风险表达或资料缺失。
]

# 固定四个质量维度；新增维度时同步更新 QUALITY_DIMENSIONS 和评分逻辑。
QualityDimension = Literal[
    "product_fidelity",  # 商品名称和画面描述是否持续引用同一商品。
    "platform_fit",  # 表达结构是否适配目标平台内容语境。
    "conversion_clarity",  # CTA、镜头时长和转化路径是否清晰。
    "compliance",  # 是否避开系统风险词和用户禁用表达。
]
QualityScore = Annotated[int, Field(ge=0, le=100)]

# 维度顺序决定聚合和展示顺序。
QUALITY_DIMENSIONS: Final[tuple[QualityDimension, ...]] = (
    "product_fidelity",  # 商品引用覆盖。
    "platform_fit",  # 平台适配。
    "conversion_clarity",  # 转化清晰度。
    "compliance",  # 风险表达检查。
)

# 自动质量门禁的最低综合分；blocked 问题会阻断通过。
QUALITY_PASSING_SCORE: Final = 80


class QualityIssue(BaseModel):
    """描述质量门禁发现的一个明确问题。"""

    severity: IssueSeverity = Field(description="问题是否阻断进入人工审核。")
    code: str = Field(description="稳定的质量问题代码。")
    message: str = Field(description="面向用户的质量问题说明。")
    recommendation: str = Field(description="Agent 应执行或用户可参考的修改建议。")


class QualityEvaluation(BaseModel):
    """保存一轮创意质量评估的聚合结果。"""

    overall_score: int = Field(ge=0, le=100, description="当前方案集合的综合质量评分。")
    dimension_scores: dict[QualityDimension, QualityScore] = Field(
        description="商品引用、平台适配、转化清晰度和合规维度评分。"
    )
    passed: bool = Field(description="是否通过自动质量门禁。")
    issues: list[QualityIssue] = Field(
        default_factory=list,
        description="质量门禁发现的问题。",
    )
    recommended_changes: list[str] = Field(
        default_factory=list,
        description="自动修订或人工审核时采用的修改建议。",
    )

    @classmethod
    def from_scores(
        cls,
        *,
        dimension_scores: dict[QualityDimension, int],
        issues: list[QualityIssue],
        recommended_changes: list[str] | None = None,
    ) -> Self:
        """从维度分和阻断问题唯一计算总分及通过状态。"""

        if set(dimension_scores) != set(QUALITY_DIMENSIONS):
            raise ValueError("质量评估必须完整包含四个规定维度。")
        overall_score = round(sum(dimension_scores.values()) / len(dimension_scores))
        passed = overall_score >= QUALITY_PASSING_SCORE and not any(
            issue.severity == "blocked" for issue in issues
        )
        return cls(
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            passed=passed,
            issues=issues,
            recommended_changes=(
                recommended_changes
                if recommended_changes is not None
                else [issue.recommendation for issue in issues]
            ),
        )

    @model_validator(mode="after")
    def validate_dimension_scores(self) -> Self:
        """校验每轮评估完整覆盖当前定义的四个质量维度。"""

        if set(self.dimension_scores) != set(QUALITY_DIMENSIONS):
            raise ValueError("质量评估必须完整包含四个规定维度。")
        expected_overall = round(sum(self.dimension_scores.values()) / len(self.dimension_scores))
        if self.overall_score != expected_overall:
            raise ValueError("质量总分必须等于四个维度评分的平均值。")
        expected_passed = expected_overall >= QUALITY_PASSING_SCORE and not any(
            issue.severity == "blocked" for issue in self.issues
        )
        if self.passed != expected_passed:
            raise ValueError("质量通过状态必须由总分和阻断问题唯一计算。")
        return self


class CreativeDecisionBundle(BaseModel):
    """定义 API 和数据库可以公开的最终 Agent 决策。"""

    action: DecisionAction = Field(description="Agent 建议用户下一步执行的动作。")
    decision_reason: str = Field(description="当前动作和方案的决策理由。")
    confidence: float = Field(ge=0, le=1, description="最终决策置信度。")
    analysis: ProductAnalysis = Field(description="最终采用的商品分析。")
    concepts: list[CreativeConcept] = Field(
        description="通过生成和修订得到的创意方案。",
    )
    storyboard_prompts: StoryboardPromptBundle = Field(
        description="由分镜 Prompt 节点生成的视频执行指令。",
    )
    evaluation: QualityEvaluation = Field(description="最终一轮自动质量评估。")
    revision_count: int = Field(
        default=0,
        ge=0,
        le=1,
        description="质量门禁触发的自动修订次数。",
    )

    @classmethod
    def from_draft_evaluation(
        cls,
        *,
        draft: CreativeDraft,
        storyboard_prompts: StoryboardPromptBundle,
        evaluation: QualityEvaluation,
        revision_count: int,
    ) -> Self:
        """根据最终质量结果选择人工审核或继续处理质量问题。"""

        return cls(
            action="review_plan" if evaluation.passed else "resolve_quality_issues",
            decision_reason=draft.decision_reason,
            confidence=draft.confidence,
            analysis=draft.analysis,
            concepts=draft.concepts,
            storyboard_prompts=storyboard_prompts,
            evaluation=evaluation,
            revision_count=revision_count,
        )

    @model_validator(mode="after")
    def validate_action_contract(self) -> Self:
        """保证下一步动作与缺失信息、方案和质量结果保持一致。"""

        if self.analysis.missing_information:
            raise ValueError(f"{self.action} 不能保留阻断生成的缺失信息。")
        if len(self.concepts) != 3:
            raise ValueError(f"{self.action} 必须包含三套完整创意方案。")
        validate_plan_concepts(self.concepts)
        if [concept.concept_key for concept in self.concepts] != [
            concept.concept_key for concept in self.storyboard_prompts.concepts
        ]:
            raise ValueError(f"{self.action} 的创意方案和分镜 Prompt 必须一一对应。")

        blocked_issues = [issue for issue in self.evaluation.issues if issue.severity == "blocked"]
        if self.action == "review_plan":
            if not self.evaluation.passed:
                raise ValueError("review_plan 必须已经通过最终质量门禁。")
            if blocked_issues:
                raise ValueError("review_plan 不能包含阻断级质量问题。")
        else:
            if self.evaluation.passed:
                raise ValueError("resolve_quality_issues 只能用于未通过最终质量门禁的方案。")
            if not self.evaluation.issues:
                raise ValueError("resolve_quality_issues 必须包含可处理的质量问题。")
        return self
