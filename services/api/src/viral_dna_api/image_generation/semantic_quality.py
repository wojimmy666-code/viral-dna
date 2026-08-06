from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..ai.billing import (
    PriceCatalog,
    PriceCatalogError,
    calculate_cost_micros,
    estimate_text_tokens,
    estimate_visual_tokens,
)
from ..ai.catalog import ModelCatalogError, default_analysis_profile, load_model_plan
from ..ai.contracts import ModelProviderError, ModelRequest
from ..ai.router import ModelRouter
from ..chinese import to_simplified
from ..models import ModelTask, ModelUsage, ShotPlan

SEMANTIC_QUALITY_SCHEMA_VERSION = "viral-dna-image-semantic-quality/v1"
DEFAULT_OUTPUT_TOKEN_ESTIMATE = 600


class SemanticQualityCheck(BaseModel):
    id: Literal[
        "subject_and_composition",
        "identity_consistency",
        "product_shape",
        "wardrobe_consistency",
        "scene_consistency",
        "text_artifacts",
    ]
    status: Literal["passed", "warning", "uncertain", "not_applicable"]
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=1, max_length=500)


class SemanticQualityPayload(BaseModel):
    status: Literal["passed", "warning", "uncertain"]
    summary: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0, le=1)
    checks: list[SemanticQualityCheck] = Field(min_length=1, max_length=8)


@dataclass(frozen=True, slots=True)
class SemanticQualityOutcome:
    report: dict[str, object]
    usage: ModelUsage
    estimated_cost_micros: int = 0
    actual_cost_micros: int = 0
    provider: str | None = None
    model: str | None = None


def _safe_text(value: object, fallback: str) -> str:
    normalized = " ".join((to_simplified(str(value)) or "").split())
    return (normalized or fallback)[:500]


def _empty_outcome(
    status: str,
    summary: str,
    *,
    error_code: str | None = None,
) -> SemanticQualityOutcome:
    report: dict[str, object] = {
        "schema_version": SEMANTIC_QUALITY_SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "confidence": 0,
        "checks": [],
        "manual_decision_required": True,
        "estimated_cost_micros": 0,
        "actual_cost_micros": 0,
    }
    if error_code:
        report["error_code"] = error_code
    return SemanticQualityOutcome(report=report, usage=ModelUsage())


class ImageSemanticQualityService:
    """Runs optional VLM review without making the human approval decision."""

    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        price_catalog: PriceCatalog | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.price_catalog = price_catalog or PriceCatalog()

    async def assess(
        self,
        *,
        shot: ShotPlan,
        candidate_path: Path,
        source_path: Path | None,
        reference_paths: tuple[Path, ...],
        reference_labels: tuple[str, ...],
        budget_remaining_micros: int | None,
    ) -> SemanticQualityOutcome:
        try:
            plan = load_model_plan(default_analysis_profile())
        except ModelCatalogError as exc:
            return _empty_outcome(
                "unavailable",
                _safe_text(exc, "VLM 模型目录不可用，保留人工质检。"),
                error_code="semantic_model_catalog_unavailable",
            )
        if plan is None:
            return _empty_outcome(
                "not_configured",
                "尚未启用 VLM，已保留人工质检。",
                error_code="semantic_model_not_configured",
            )
        targets = plan.targets_for(ModelTask.IMAGE_QUALITY_QA)
        if not targets:
            return _empty_outcome(
                "not_configured",
                "模型计划没有图片语义质检路由，已保留人工质检。",
                error_code="semantic_route_missing",
            )
        if plan.pricing_version != self.price_catalog.catalog_version:
            return _empty_outcome(
                "unavailable",
                "VLM 价格版本不一致，已在调用前停止并保留人工质检。",
                error_code="semantic_pricing_version_mismatch",
            )

        target = targets[0]
        paths = [candidate_path]
        labels = ["图片1：待质检的 AI 生成候选"]
        if source_path is not None and await asyncio.to_thread(
            source_path.is_file
        ):
            paths.append(source_path)
            labels.append("图片2：原视频分镜关键帧")
        for path, label in zip(reference_paths[:6], reference_labels[:6], strict=False):
            if await asyncio.to_thread(path.is_file) and path not in paths:
                paths.append(path)
                labels.append(f"图片{len(paths)}：参考资产 {label}")

        user_prompt = (
            f"分镜图片提示词：{shot.image_prompt.strip()}\n"
            "比较候选图、原关键帧与参考资产。检查主体构图、人物身份、产品结构、"
            "服装、场景和异常文字。没有相应参考时标记 not_applicable；证据不足时"
            "标记 uncertain，禁止猜测。只输出符合 Schema 的 JSON。"
        )
        system_prompt = (
            "你是短视频分镜生成图的质量复核员。输出简体中文结构化 JSON。"
            "你只提供辅助证据，不得替代人工审批，不得因为低置信度自动拒绝图片。"
        )
        estimated_usage = ModelUsage(
            input_tokens=(
                estimate_text_tokens(system_prompt + user_prompt)
                + estimate_visual_tokens(image_count=len(paths), width=640, height=640)
            ),
            output_tokens=DEFAULT_OUTPUT_TOKEN_ESTIMATE,
            image_count=len(paths),
        )
        estimated_usage.total_tokens = (
            estimated_usage.input_tokens + estimated_usage.output_tokens
        )
        try:
            estimated_price = self.price_catalog.snapshot_for(
                target.provider,
                target.model,
                estimated_usage.input_tokens,
            )
        except PriceCatalogError as exc:
            return _empty_outcome(
                "unavailable",
                _safe_text(exc, "VLM 缺少可验证价格，已在调用前停止。"),
                error_code="semantic_price_missing",
            )
        estimated_cost = calculate_cost_micros(estimated_usage, estimated_price)
        if (
            budget_remaining_micros is not None
            and estimated_cost > max(0, budget_remaining_micros)
        ):
            outcome = _empty_outcome(
                "skipped_budget",
                "VLM 质检预计费用超过项目剩余预算，未发起调用并保留人工质检。",
                error_code="semantic_budget_exceeded",
            )
            outcome.report["estimated_cost_micros"] = estimated_cost
            return SemanticQualityOutcome(
                report=outcome.report,
                usage=estimated_usage,
                estimated_cost_micros=estimated_cost,
                provider=target.provider,
                model=target.model,
            )

        try:
            provider = self.router.provider_for(target)
            result = await provider.generate(
                ModelRequest(
                    task=ModelTask.IMAGE_QUALITY_QA,
                    target=target,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    image_paths=tuple(paths),
                    image_labels=tuple(labels),
                ),
                SemanticQualityPayload,
            )
            try:
                measured_price = self.price_catalog.snapshot_for(
                    target.provider,
                    result.resolved_model,
                    result.usage.input_tokens,
                )
            except PriceCatalogError:
                measured_price = self.price_catalog.snapshot_for(
                    target.provider,
                    target.model,
                    result.usage.input_tokens,
                )
            actual_cost = calculate_cost_micros(result.usage, measured_price)
            payload = result.data.model_dump(mode="json")
            report = {
                "schema_version": SEMANTIC_QUALITY_SCHEMA_VERSION,
                "status": payload["status"],
                "summary": _safe_text(payload["summary"], "VLM 质检已完成。"),
                "confidence": payload["confidence"],
                "checks": payload["checks"],
                "manual_decision_required": True,
                "provider": target.provider,
                "requested_model": target.model,
                "resolved_model": result.resolved_model,
                "provider_request_id": result.provider_request_id,
                "usage": result.usage.model_dump(mode="json"),
                "estimated_cost_micros": estimated_cost,
                "actual_cost_micros": actual_cost,
                "latency_ms": result.latency_ms,
            }
            return SemanticQualityOutcome(
                report=report,
                usage=result.usage,
                estimated_cost_micros=estimated_cost,
                actual_cost_micros=actual_cost,
                provider=target.provider,
                model=result.resolved_model,
            )
        except ModelProviderError as exc:
            usage = exc.usage or ModelUsage()
            actual_cost = 0
            if exc.usage is not None:
                try:
                    failure_price = self.price_catalog.snapshot_for(
                        target.provider,
                        exc.resolved_model or target.model,
                        exc.usage.input_tokens,
                    )
                    actual_cost = calculate_cost_micros(exc.usage, failure_price)
                except PriceCatalogError:
                    actual_cost = 0
            report = {
                "schema_version": SEMANTIC_QUALITY_SCHEMA_VERSION,
                "status": "unavailable",
                "summary": _safe_text(exc, "VLM 质检失败，已保留人工质检。"),
                "confidence": 0,
                "checks": [],
                "manual_decision_required": True,
                "error_code": exc.code,
                "provider": target.provider,
                "requested_model": target.model,
                "resolved_model": exc.resolved_model,
                "provider_request_id": exc.provider_request_id,
                "usage": usage.model_dump(mode="json"),
                "estimated_cost_micros": estimated_cost,
                "actual_cost_micros": actual_cost,
                "latency_ms": exc.latency_ms,
            }
            return SemanticQualityOutcome(
                report=report,
                usage=usage,
                estimated_cost_micros=estimated_cost,
                actual_cost_micros=actual_cost,
                provider=target.provider,
                model=exc.resolved_model or target.model,
            )
