from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from .contracts import (
    Artifact,
    AssetUsage,
    AssetUsageListUpdate,
    AudioAsset,
    AudioAssetCreate,
    AudioCaptionUpdate,
    BrandSnapshot,
    BrandSnapshotCreate,
    ClaimEvidence,
    ClaimEvidenceListUpdate,
    CreativeBriefInput,
    CreativeBriefRevision,
    DeliveryFromExportRequest,
    DeliveryManifest,
    DeliveryManifestCreate,
    DependencyImpactRequest,
    DependencyImpactResponse,
    GateDecision,
    GateDecisionRequest,
    LookTest,
    LookTestSelection,
    OutlineRevision,
    OutlineUpdate,
    PictureLockRequest,
    PreflightResult,
    ProductionAudioCaptionFinalize,
    ProductionPictureLockRequest,
    RunContractInput,
    RunContractRevision,
    ShotManifestRevision,
    ShotManifestUpdate,
    ShotPromptRewriteRequest,
    SkillGate,
    SkillOperationsSummary,
    SkillProjectWorkspace,
    SkillRunCreate,
    SkillRunDetail,
    SkillRunMetrics,
    SkillStepRun,
    TimelineV3Revision,
)
from .service import SkillWorkflowService, SkillWorkflowServiceError


def _raise_http(exc: SkillWorkflowServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
        },
    ) from exc


def create_skill_workflow_router(service: SkillWorkflowService) -> APIRouter:
    router = APIRouter(tags=["skill-workflow"])

    @router.get(
        "/projects/{project_id}/skill-workspace",
        response_model=SkillProjectWorkspace,
    )
    async def get_workspace(project_id: UUID) -> SkillProjectWorkspace:
        try:
            return await service.workspace(project_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/projects/{project_id}/brand-snapshot",
        response_model=BrandSnapshot,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_brand_snapshot(
        project_id: UUID,
        payload: BrandSnapshotCreate,
    ) -> BrandSnapshot:
        try:
            return await service.create_brand_snapshot(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/brief",
        response_model=CreativeBriefRevision,
    )
    async def put_brief(
        project_id: UUID,
        payload: CreativeBriefInput,
    ) -> CreativeBriefRevision:
        try:
            return await service.put_brief(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/asset-usages",
        response_model=list[AssetUsage],
    )
    async def put_asset_usages(
        project_id: UUID,
        payload: AssetUsageListUpdate,
    ) -> list[AssetUsage]:
        try:
            return await service.replace_asset_usages(project_id, payload.items)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/claim-evidence",
        response_model=list[ClaimEvidence],
    )
    async def put_claims(
        project_id: UUID,
        payload: ClaimEvidenceListUpdate,
    ) -> list[ClaimEvidence]:
        try:
            return await service.replace_claims(project_id, payload.items)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/run-contract",
        response_model=RunContractRevision,
    )
    async def put_run_contract(
        project_id: UUID,
        payload: RunContractInput,
    ) -> RunContractRevision:
        try:
            return await service.put_run_contract(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/projects/{project_id}/preflight",
        response_model=PreflightResult,
    )
    async def preflight(project_id: UUID) -> PreflightResult:
        try:
            return await service.preflight(project_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/projects/{project_id}/skill-runs",
        response_model=SkillRunDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def start_run(
        project_id: UUID,
        payload: SkillRunCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> SkillRunDetail:
        if idempotency_key:
            payload = payload.model_copy(update={"idempotency_key": idempotency_key})
        try:
            return await service.start_run(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.get("/skill-runs/{run_id}", response_model=SkillRunDetail)
    async def get_run(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.run_detail(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.get("/skill-runs/{run_id}/metrics", response_model=SkillRunMetrics)
    async def get_run_metrics(run_id: UUID) -> SkillRunMetrics:
        try:
            return await service.run_metrics(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.get("/skill-runs/{run_id}/events")
    async def run_events(
        run_id: UUID,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        async def stream():
            try:
                detail = await service.run_detail(run_id)
                payload = detail.model_dump(mode="json")
                sequence = max(after + 1, detail.run.last_event_sequence + 1)
                encoded = json.dumps(payload, ensure_ascii=False)
                yield f"id: {sequence}\nevent: snapshot\ndata: {encoded}\n\n"
            except SkillWorkflowServiceError as exc:
                payload = {"code": exc.code, "message": str(exc)}
                yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.post("/skill-runs/{run_id}/style/compile", response_model=SkillRunDetail)
    async def compile_style(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.compile_style(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/look-test/generate",
        response_model=LookTest,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def generate_look_test(run_id: UUID) -> LookTest:
        try:
            return await service.start_look_test_generation(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post("/skill-runs/{run_id}/look-test/cancel", response_model=LookTest)
    async def cancel_look_test(run_id: UUID) -> LookTest:
        try:
            return await service.cancel_look_test_generation(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post("/skill-runs/{run_id}/look-test/select", response_model=LookTest)
    async def select_look_test(run_id: UUID, payload: LookTestSelection) -> LookTest:
        try:
            return await service.select_look_test(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/storyboard/compile",
        response_model=SkillRunDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def compile_storyboard(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.compile_storyboard(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/storyboard/cancel",
        response_model=SkillRunDetail,
    )
    async def cancel_storyboard(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.cancel_storyboard(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/storyboard/shots/{shot_key}/rewrite",
        response_model=ShotManifestRevision,
    )
    async def rewrite_storyboard_shot(
        run_id: UUID,
        shot_key: str,
        payload: ShotPromptRewriteRequest,
    ) -> ShotManifestRevision:
        try:
            return await service.rewrite_storyboard_shot(run_id, shot_key, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/outline",
        response_model=OutlineRevision,
    )
    async def put_outline(project_id: UUID, payload: OutlineUpdate) -> OutlineRevision:
        try:
            return await service.put_outline(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/projects/{project_id}/shot-manifest",
        response_model=ShotManifestRevision,
    )
    async def put_shot_manifest(
        project_id: UUID,
        payload: ShotManifestUpdate,
    ) -> ShotManifestRevision:
        try:
            return await service.put_shot_manifest(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/gates/{gate}/decision",
        response_model=GateDecision,
    )
    async def decide_gate(
        run_id: UUID,
        gate: SkillGate,
        payload: GateDecisionRequest,
    ) -> GateDecision:
        try:
            return await service.decide_gate(run_id, gate, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/picture-lock",
        response_model=TimelineV3Revision,
    )
    async def picture_lock(
        run_id: UUID,
        payload: PictureLockRequest,
    ) -> TimelineV3Revision:
        try:
            return await service.picture_lock(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/picture-lock/from-production",
        response_model=TimelineV3Revision,
    )
    async def picture_lock_from_production(
        run_id: UUID,
        payload: ProductionPictureLockRequest,
    ) -> TimelineV3Revision:
        try:
            return await service.picture_lock_from_production(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/projects/{project_id}/audio-assets",
        response_model=AudioAsset,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_audio_asset(
        project_id: UUID,
        payload: AudioAssetCreate,
    ) -> AudioAsset:
        try:
            return await service.create_audio_asset(project_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.put(
        "/skill-runs/{run_id}/audio-caption",
        response_model=TimelineV3Revision,
    )
    async def put_audio_caption(
        run_id: UUID,
        payload: AudioCaptionUpdate,
    ) -> TimelineV3Revision:
        try:
            return await service.put_audio_caption(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/audio-caption/from-production",
        response_model=TimelineV3Revision,
    )
    async def finalize_audio_caption_from_production(
        run_id: UUID,
        payload: ProductionAudioCaptionFinalize,
    ) -> TimelineV3Revision:
        try:
            return await service.finalize_audio_caption_from_production(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/delivery-manifest",
        response_model=DeliveryManifest,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_delivery_manifest(
        run_id: UUID,
        payload: DeliveryManifestCreate,
    ) -> DeliveryManifest:
        try:
            return await service.create_delivery_manifest(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/delivery-manifest/from-export",
        response_model=DeliveryManifest,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_delivery_from_export(
        run_id: UUID,
        payload: DeliveryFromExportRequest,
    ) -> DeliveryManifest:
        try:
            return await service.create_delivery_from_export(run_id, payload)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post("/skill-runs/{run_id}/cancel", response_model=SkillRunDetail)
    async def cancel_run(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.cancel(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post("/skill-runs/{run_id}/resume", response_model=SkillRunDetail)
    async def resume_run(run_id: UUID) -> SkillRunDetail:
        try:
            return await service.resume(run_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-runs/{run_id}/steps/{step_id}/retry",
        response_model=SkillStepRun,
    )
    async def retry_step(run_id: UUID, step_id: UUID) -> SkillStepRun:
        try:
            return await service.retry_step(run_id, step_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.get("/projects/{project_id}/artifacts", response_model=list[Artifact])
    async def list_artifacts(project_id: UUID) -> list[Artifact]:
        try:
            await service.workspace(project_id)
            return await service.repository.list_skill_artifacts(project_id)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    @router.post(
        "/projects/{project_id}/dependency-impact",
        response_model=DependencyImpactResponse,
    )
    async def dependency_impact(
        project_id: UUID,
        payload: DependencyImpactRequest,
    ) -> DependencyImpactResponse:
        try:
            await service.workspace(project_id)
            return await service.mark_dependency_stale(payload, apply=False)
        except SkillWorkflowServiceError as exc:
            _raise_http(exc)

    return router


def create_skill_workflow_admin_router(service: SkillWorkflowService) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["skill-workflow-admin"])

    @router.get("/skill-operations", response_model=SkillOperationsSummary)
    async def skill_operations() -> SkillOperationsSummary:
        return await service.operations_summary()

    return router
