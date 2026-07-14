"""实现 prompt_check 节点：评估 Prompt 风险并执行一次自动修订。"""

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.modeling.provider import ModelGenerationError
from app.agents.modeling.review import build_confirmed_fact_registry, review_creative_claims
from app.agents.nodes import REVIEW_COST_GATE
from app.agents.rules.analysis import restore_inputs, split_phrases
from app.agents.rules.quality import (
    aggregate_evaluations,
    apply_semantic_claim_review,
    evaluate_concept,
    revise_draft,
    semantic_review_unavailable,
)
from app.agents.state import AgentState, PlannerContext, read_draft
from app.application.creative_agent import CreativeDraft, QualityEvaluation


def prompt_check_node(
    state: AgentState,
    runtime: Runtime[PlannerContext],
) -> Command:
    """评估三套方案，必要时修订一次，并把质量结论写回 checkpoint。"""

    project, brief, _ = restore_inputs(state)
    forbidden_words = split_phrases(brief.forbidden_words_text if brief else "")
    confirmed_facts = list(build_confirmed_fact_registry(brief).values()) if brief else []
    draft = read_draft(state)
    revision_count = state["revision_count"]
    evaluation = _evaluate_draft(
        draft,
        expected_duration=project.duration_seconds,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )

    if not evaluation.passed and revision_count < 1:
        # 自动修订执行确定性修复，并控制在一次修订内。
        draft = revise_draft(
            draft=draft,
            evaluation=evaluation,
            product_name=draft.analysis.product_summary,
            forbidden_words=forbidden_words,
        )
        revision_count += 1
        evaluation = _evaluate_draft(
            draft,
            expected_duration=project.duration_seconds,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )

    # 只有外部模型实际生成的草案需要第二模型语义复核；本地模板仅使用服务端事实。
    if evaluation.passed and state["provider_key"] == "openai_compatible":
        if brief is None:
            evaluation = semantic_review_unavailable(evaluation)
        else:
            try:
                review, confirmed_fact_registry = review_creative_claims(
                    provider=runtime.context.provider,
                    draft=draft,
                    brief=brief,
                )
                evaluation = apply_semantic_claim_review(
                    evaluation,
                    review=review,
                    confirmed_facts=confirmed_fact_registry,
                )
            except ModelGenerationError:
                evaluation = semantic_review_unavailable(evaluation)

    return Command(
        update={
            "draft": draft.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json"),
            "revision_count": revision_count,
        },
        goto=REVIEW_COST_GATE,
    )


def _evaluate_draft(
    draft: CreativeDraft,
    *,
    expected_duration: int,
    forbidden_words: list[str],
    confirmed_facts: list[str],
) -> QualityEvaluation:
    """按方案顺序执行确定性评估并聚合为唯一质量结论。"""

    # 质量门禁按 concepts 原始顺序执行，保证结果稳定、可复现。
    evaluations = [
        evaluate_concept(
            concept=concept,
            product_summary=draft.analysis.product_summary,
            expected_duration=expected_duration,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )
        for concept in draft.concepts
    ]
    return aggregate_evaluations(evaluations)
