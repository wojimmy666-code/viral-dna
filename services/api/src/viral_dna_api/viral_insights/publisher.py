from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from viral_dna_api.models import (
    ProductionProjectCreate,
    ShotPlanBulkItem,
    ShotPlanBulkUpdate,
)
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.production_seeds.contracts import (
    ProductionSeedShot,
    canonical_digest,
    seconds_to_frame,
)

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
        visual_style_snapshot: dict | None = None,
    ) -> ViralConceptPublishResult:
        try:
            if concept.strategy == "creative":
                return await self._publish_creative(analysis_id, concept, payload, visual_style_snapshot)
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

    async def _publish_creative(self, analysis_id, concept, payload, visual_style_snapshot=None):
        shots = []
        cursor = 0
        for index, shot in enumerate(concept.shots, start=1):
            duration = max(1, seconds_to_frame(shot.duration_seconds, 30))
            material = {
                "stable_shot_key": "shot_"
                + sha256(f"{concept.id}:{index}".encode()).hexdigest()[:24],
                "order": index,
                "narrative_role": shot.traffic_role[:80],
                "start_frame": cursor,
                "duration_frames": duration,
                "description": shot.title,
                "image_prompt": shot.image_prompt,
                "video_prompt": shot.video_prompt,
                "image_negative_constraints": list(dict.fromkeys(shot.negative_constraints)),
                "video_negative_constraints": list(dict.fromkeys(shot.negative_constraints)),
            }
            shots.append(ProductionSeedShot(**material, input_hash=canonical_digest(material)))
            cursor += duration
        detail = await self.production_service.create_project(
            payload.record_id,
            ProductionProjectCreate(
                base_analysis_id=analysis_id,
                name=payload.name or concept.name[:120],
                output_aspect_ratio=payload.output_aspect_ratio,
                budget_limit_micros=payload.budget_limit_micros,
            ),
            authored_shots=shots,
            creative_brief={**concept.model_dump(mode="json"), "visual_style_snapshot": visual_style_snapshot or {}},
        )
        return ViralConceptPublishResult(
            project_id=detail.project.id,
            project_name=detail.project.name,
            concept_id=concept.id,
            shot_count=len(shots),
        )
