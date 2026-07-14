from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.application.creative_agent import (
    CreativeConcept,
    CreativeDraft,
    ProductAnalysis,
    ShotPlan,
)


def _concept(key: str) -> CreativeConcept:
    return CreativeConcept(
        concept_key=key,
        title=f"方案 {key}",
        strategy="用商品事实组织三个镜头。",
        hook="先看这个商品细节。",
        reasoning="适合目标平台的短视频节奏。",
        primary_selling_point="轻便易携",
        target_audience="通勤人群",
        call_to_action="按需查看商品详情。",
        shots=[
            ShotPlan(
                order=order,
                duration_seconds=duration,
                purpose="展示商品事实",
                visual="便携保温杯清晰出现在画面中",
                caption="轻便易携",
                generation_mode="image_to_video",
            )
            for order, duration in ((1, 3), (2, 7), (3, 5))
        ],
    )


def _draft() -> CreativeDraft:
    return CreativeDraft(
        decision_reason="围绕通勤场景形成三套差异化方向。",
        confidence=0.88,
        concepts=[_concept("one"), _concept("two"), _concept("three")],
        analysis=ProductAnalysis(
            product_summary="便携保温杯",
            inferred_category="强调转化的消费品",
            inferred_selling_points=["轻便易携"],
            inferred_audience=["通勤人群"],
            visual_evidence_count=1,
            constraints=[],
            missing_information=[],
            readiness_score=100,
        ),
    )


def test_plan_rejects_duplicate_concept_keys() -> None:
    payload = _draft().model_dump()
    payload["concepts"][1]["concept_key"] = payload["concepts"][0]["concept_key"]

    with pytest.raises(ValidationError, match="concept_key 必须唯一"):
        CreativeDraft.model_validate(payload)


def test_plan_rejects_shots_that_are_not_stored_in_execution_order() -> None:
    payload = deepcopy(_draft().model_dump())
    payload["concepts"][0]["shots"] = [
        payload["concepts"][0]["shots"][2],
        payload["concepts"][0]["shots"][0],
        payload["concepts"][0]["shots"][1],
    ]

    with pytest.raises(ValidationError, match="必须依次为 1、2、3"):
        CreativeDraft.model_validate(payload)
