from __future__ import annotations

from typing import Protocol
from uuid import UUID

from viral_dna_api.models import AnalysisReport

from .concept_strategies import (
    CONCEPT_GENERATOR_ID,
    CONCEPT_SCHEMA_VERSION,
    STRATEGY_CONTRACT_VERSION,
    ConceptDiversityError,
)
from .contracts import (
    ViralConcept,
    ViralConceptGenerateRequest,
    ViralConceptPublishRequest,
    ViralConceptPublishResult,
    ViralConceptSet,
    ViralInsightReport,
)
from .engine import build_concept_set, build_viral_insight, report_fingerprint


class ViralInsightRepository(Protocol):
    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None: ...

    async def save_viral_insight(self, report: ViralInsightReport) -> ViralInsightReport: ...

    async def get_viral_insight(self, analysis_id: UUID) -> ViralInsightReport | None: ...

    async def save_viral_concept_set(self, concepts: ViralConceptSet) -> ViralConceptSet: ...

    async def get_viral_concept_set(self, concept_set_id: UUID) -> ViralConceptSet | None: ...

    async def list_viral_concept_sets(self, analysis_id: UUID) -> list[ViralConceptSet]: ...


class ViralConceptPublisher(Protocol):
    async def publish(
        self,
        *,
        analysis_id: UUID,
        concept: ViralConcept,
        payload: ViralConceptPublishRequest,
    ) -> ViralConceptPublishResult: ...


class ViralInsightServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _concept_set_stale_reason(
    concept_set: ViralConceptSet,
    insight: ViralInsightReport,
) -> str | None:
    if (
        concept_set.schema_version != CONCEPT_SCHEMA_VERSION
        or concept_set.generator_id != CONCEPT_GENERATOR_ID
        or concept_set.strategy_contract_version != STRATEGY_CONTRACT_VERSION
    ):
        return "该批次由旧版方案生成器创建，三套策略可能存在重复，请重新生成"
    if concept_set.source_insight_fingerprint != insight.input_fingerprint:
        return "分析报告已更新，该批次提示词不再对应当前分析，请重新生成"
    return None


def _mark_stale(
    concept_set: ViralConceptSet,
    insight: ViralInsightReport,
) -> ViralConceptSet:
    reason = _concept_set_stale_reason(concept_set, insight)
    if reason is None or concept_set.status == "failed":
        return concept_set
    return concept_set.model_copy(update={"status": "stale", "stale_reason": reason})


class ViralInsightService:
    def __init__(
        self,
        repository: ViralInsightRepository,
        publisher: ViralConceptPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher

    async def _source_report(self, analysis_id: UUID) -> AnalysisReport:
        report = await self.repository.get_report_by_analysis(analysis_id)
        if report is None:
            raise ViralInsightServiceError(
                404,
                "analysis_report_not_found",
                "分析报告不存在，请先完成视频分析",
            )
        return report

    async def get_insight(self, analysis_id: UUID) -> ViralInsightReport:
        source = await self._source_report(analysis_id)
        current = await self.repository.get_viral_insight(analysis_id)
        fingerprint = report_fingerprint(source)
        if current is not None and current.input_fingerprint == fingerprint:
            return current
        generated = build_viral_insight(source)
        return await self.repository.save_viral_insight(generated)

    async def refresh_insight(self, analysis_id: UUID) -> ViralInsightReport:
        source = await self._source_report(analysis_id)
        generated = build_viral_insight(source)
        return await self.repository.save_viral_insight(generated)

    async def latest_concepts(self, analysis_id: UUID) -> ViralConceptSet | None:
        insight = await self.get_insight(analysis_id)
        items = await self.repository.list_viral_concept_sets(analysis_id)
        if not items:
            return None
        current_items = [
            item
            for item in items
            if _concept_set_stale_reason(item, insight) is None and item.status == "completed"
        ]
        supported_items = [
            item
            for item in items
            if item.schema_version == CONCEPT_SCHEMA_VERSION
            and item.generator_id == CONCEPT_GENERATOR_ID
            and item.strategy_contract_version == STRATEGY_CONTRACT_VERSION
        ]
        selected = max(current_items or supported_items or items, key=lambda item: item.created_at)
        return _mark_stale(selected, insight)

    async def generate_concepts(
        self,
        analysis_id: UUID,
        payload: ViralConceptGenerateRequest,
    ) -> ViralConceptSet:
        source = await self._source_report(analysis_id)
        insight = await self.get_insight(analysis_id)
        known_entities = {item.entity_id for item in insight.replacement_opportunities}
        unknown = [
            item.entity_id for item in payload.replacements if item.entity_id not in known_entities
        ]
        if unknown:
            raise ViralInsightServiceError(
                422,
                "replacement_entity_not_found",
                "替换清单包含当前分析中不存在的元素",
            )
        try:
            concept_set = build_concept_set(
                source,
                insight,
                payload.strategies,
                payload.replacements,
            )
        except ConceptDiversityError as exc:
            raise ViralInsightServiceError(
                422,
                "concept_diversity_failed",
                str(exc),
            ) from exc
        return await self.repository.save_viral_concept_set(concept_set)

    async def publish_concept(
        self,
        concept_set_id: UUID,
        concept_id: UUID,
        payload: ViralConceptPublishRequest,
    ) -> ViralConceptPublishResult:
        concept_set = await self.repository.get_viral_concept_set(concept_set_id)
        if concept_set is None:
            raise ViralInsightServiceError(404, "concept_set_not_found", "复刻方案批次不存在")
        insight = await self.get_insight(concept_set.analysis_id)
        stale_reason = _concept_set_stale_reason(concept_set, insight)
        if stale_reason is not None or concept_set.status == "stale":
            raise ViralInsightServiceError(
                409,
                "concept_set_stale",
                stale_reason or concept_set.stale_reason or "复刻方案已过期，请重新生成",
            )
        if concept_set.status != "completed":
            raise ViralInsightServiceError(
                409,
                "concept_set_not_ready",
                "复刻方案尚未成功生成，不能创建创作方案",
            )
        concept = next((item for item in concept_set.concepts if item.id == concept_id), None)
        if concept is None:
            raise ViralInsightServiceError(404, "concept_not_found", "复刻方案不存在")
        if self.publisher is None:
            raise ViralInsightServiceError(
                503,
                "concept_publisher_unavailable",
                "创作方案发布服务尚未就绪",
            )
        return await self.publisher.publish(
            analysis_id=concept_set.analysis_id,
            concept=concept,
            payload=payload,
        )
