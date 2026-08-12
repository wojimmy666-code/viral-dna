from __future__ import annotations

from typing import Protocol
from uuid import UUID

from viral_dna_api.models import AnalysisReport

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
        await self._source_report(analysis_id)
        items = await self.repository.list_viral_concept_sets(analysis_id)
        return max(items, key=lambda item: item.created_at, default=None)

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
        concept_set = build_concept_set(
            source,
            insight,
            payload.strategies,
            payload.replacements,
        )
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
