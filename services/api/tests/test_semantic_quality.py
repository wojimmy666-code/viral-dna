from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.ai.contracts import ProviderResult
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.image_generation.semantic_quality import (
    ImageSemanticQualityService,
    SemanticQualityCheck,
    SemanticQualityPayload,
)
from viral_dna_api.models import ModelUsage, ShotPlan


class FakeQualityProvider:
    provider_id = "dashscope"

    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request, response_schema):
        self.requests.append(request)
        assert response_schema is SemanticQualityPayload
        return ProviderResult(
            data=SemanticQualityPayload(
                status="warning",
                summary="人物一致，但产品文字存在疑似伪影。",
                confidence=0.86,
                checks=[
                    SemanticQualityCheck(
                        id="identity_consistency",
                        status="passed",
                        confidence=0.91,
                        evidence="候选人物五官与人物参考相符。",
                    ),
                    SemanticQualityCheck(
                        id="text_artifacts",
                        status="warning",
                        confidence=0.82,
                        evidence="产品标签边缘出现不可辨识字符。",
                    ),
                ],
            ),
            usage=ModelUsage(
                input_tokens=1200,
                output_tokens=180,
                total_tokens=1380,
                image_count=len(request.image_paths),
            ),
            requested_model=request.target.model,
            resolved_model=request.target.model,
            provider_request_id="qa-request-1",
            latency_ms=125,
            raw_content="{}",
        )


def _shot() -> ShotPlan:
    return ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-1",
        index=1,
        start_seconds=0,
        end_seconds=2,
        duration_seconds=2,
        image_prompt="保持人物身份，替换手中产品。",
    )


@pytest.mark.asyncio
async def test_semantic_quality_returns_evidence_usage_and_measured_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.setenv("VIRAL_DNA_VLM_MODEL_ALIAS", "qwen36flash")
    candidate = tmp_path / "candidate.jpg"
    source = tmp_path / "source.jpg"
    reference = tmp_path / "person.jpg"
    for path in (candidate, source, reference):
        path.write_bytes(b"test-image-bytes")
    provider = FakeQualityProvider()
    service = ImageSemanticQualityService(
        router=ModelRouter({"dashscope": provider}),
    )

    outcome = await service.assess(
        shot=_shot(),
        candidate_path=candidate,
        source_path=source,
        reference_paths=(reference,),
        reference_labels=("identity：人物",),
        budget_remaining_micros=1_000_000,
    )
    assert outcome.report["status"] == "warning"
    assert outcome.report["manual_decision_required"] is True
    assert outcome.report["provider_request_id"] == "qa-request-1"
    assert outcome.usage.total_tokens == 1380
    assert outcome.estimated_cost_micros > 0
    assert outcome.actual_cost_micros > 0
    assert provider.requests[0].task == "image_quality_qa"
    assert len(provider.requests[0].image_paths) == 3


@pytest.mark.asyncio
async def test_semantic_quality_budget_gate_stops_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.setenv("VIRAL_DNA_VLM_MODEL_ALIAS", "qwen36flash")
    candidate = tmp_path / "candidate.jpg"
    candidate.write_bytes(b"test-image-bytes")
    provider = FakeQualityProvider()
    service = ImageSemanticQualityService(
        router=ModelRouter({"dashscope": provider}),
    )

    outcome = await service.assess(
        shot=_shot(),
        candidate_path=candidate,
        source_path=None,
        reference_paths=(),
        reference_labels=(),
        budget_remaining_micros=0,
    )
    assert outcome.report["status"] == "skipped_budget"
    assert outcome.actual_cost_micros == 0
    assert provider.requests == []
