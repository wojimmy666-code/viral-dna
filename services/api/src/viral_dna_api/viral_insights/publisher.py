from __future__ import annotations

from uuid import UUID

from viral_dna_api.models import (
    ProductionProjectCreate,
    ShotPlanBulkItem,
    ShotPlanBulkUpdate,
)
from viral_dna_api.production import ProductionService, ProductionServiceError

from .contracts import (
    ViralConcept,
    ViralConceptPublishRequest,
    ViralConceptPublishResult,
)
from .service import ViralInsightServiceError


class ProductionConceptPublisher:
    """Narrow adapter from viral concepts into the existing production domain."""

    def __init__(self, production_service: ProductionService) -> None:
        self.production_service = production_service

    async def publish(
        self,
        *,
        analysis_id: UUID,
        concept: ViralConcept,
        payload: ViralConceptPublishRequest,
    ) -> ViralConceptPublishResult:
        try:
            detail = await self.production_service.create_project(
                payload.record_id,
                ProductionProjectCreate(
                    base_analysis_id=analysis_id,
                    name=payload.name or concept.name,
                    output_aspect_ratio=payload.output_aspect_ratio,
                    budget_limit_micros=payload.budget_limit_micros,
                ),
            )
            if detail.current_revision is None:
                raise ViralInsightServiceError(
                    409,
                    "production_revision_missing",
                    "创作方案已创建，但缺少可写入的初始版本",
                )
            production_shots = await self.production_service.list_shots(detail.project.id)
            concept_by_source = {item.source_shot_id: item for item in concept.shots}
            concept_by_index = {item.index: item for item in concept.shots}
            updates = []
            for response in production_shots:
                plan = response.plan
                concept_shot = concept_by_source.get(plan.source_shot_id or "")
                if concept_shot is None:
                    concept_shot = concept_by_index.get(plan.index)
                if concept_shot is None:
                    continue
                updates.append(
                    ShotPlanBulkItem(
                        shot_plan_id=plan.id,
                        image_prompt=concept_shot.image_prompt,
                        image_negative_constraints=concept_shot.negative_constraints,
                        video_prompt=concept_shot.video_prompt,
                        video_negative_constraints=concept_shot.negative_constraints,
                    )
                )
            if not updates:
                raise ViralInsightServiceError(
                    409,
                    "production_shot_mapping_failed",
                    "复刻方案与创作分镜无法对应",
                )
            await self.production_service.bulk_update_shots(
                detail.project.id,
                ShotPlanBulkUpdate(
                    expected_revision_id=detail.current_revision.id,
                    updates=updates,
                ),
            )
            return ViralConceptPublishResult(
                project_id=detail.project.id,
                project_name=detail.project.name,
                concept_id=concept.id,
                shot_count=len(updates),
            )
        except ViralInsightServiceError:
            raise
        except ProductionServiceError as exc:
            raise ViralInsightServiceError(exc.status_code, exc.code, str(exc)) from exc
