from __future__ import annotations

import asyncio
import hashlib
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ..category_profiles.contracts import CategoryProfileSnapshot
from ..category_profiles.service import CategoryProfileService, CategoryProfileServiceError
from ..image_generation import ImageGenerationGateway, ImageGenerationGatewayError
from ..image_generation.catalog import ImageModelCatalogError, load_image_model_catalog
from ..models import (
    GenerationCandidate,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ImageGenerationCreate,
    ImageGenerationInputMode,
    ProductionAdvanceRequest,
    ProductionOriginType,
    ProductionProject,
    ProductionRunStatus,
    ProductionStep,
    ProductionTimeline,
    ShotPlan,
    ShotSourceKind,
    ShotVisualBeat,
    TimelineRenderJob,
    VideoGenerationAudioStrategy,
    VideoGenerationCreate,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
    WorkflowItemStatus,
)
from ..platform_skills.contracts import SkillVersionSnapshot
from ..production_seeds import (
    ProductionSeedAudioIntent,
    ProductionSeedReference,
    ProductionSeedShot,
    ProductionSeedSubtitleIntent,
    SkillProductionSeedBuilder,
    seconds_to_frame,
)
from ..projects import ProjectKind, ProjectService, ProjectStage, ProjectStatus
from ..projects.contracts import Project
from ..video_generation.catalog import VideoModelCatalogError, load_video_model_catalog
from ..workspace_catalog import AccountContextService
from .contracts import (
    GATE_ORDER,
    STAGE_BY_GATE,
    Artifact,
    ArtifactDependency,
    AssetUsage,
    AssetUsageInput,
    AudioAsset,
    AudioAssetCreate,
    AudioCaptionUpdate,
    BrandSnapshot,
    BrandSnapshotCreate,
    ClaimEvidence,
    ClaimEvidenceInput,
    ClaimStatus,
    CreativeBriefInput,
    CreativeBriefRevision,
    CreativeTreatmentRevision,
    DeliveryFromExportRequest,
    DeliveryManifest,
    DeliveryManifestCreate,
    DependencyImpactRequest,
    DependencyImpactResponse,
    ExecutionStatus,
    Fidelity,
    FrameRate,
    GateActorType,
    GateDecision,
    GateDecisionRequest,
    GateDecisionValue,
    LookTest,
    LookTestItem,
    LookTestSelection,
    MixRevision,
    OutlineBeat,
    OutlineRevision,
    OutlineUpdate,
    PictureLockRequest,
    PreflightIssue,
    PreflightResult,
    ProductionAudioCaptionFinalize,
    ProductionPictureLockRequest,
    ReviewStatus,
    RightsStatus,
    RunContractInput,
    RunContractRevision,
    ShotManifestRevision,
    ShotManifestShot,
    ShotManifestUpdate,
    SkillGate,
    SkillOperationMetrics,
    SkillOperationsSummary,
    SkillProjectWorkspace,
    SkillRun,
    SkillRunCreate,
    SkillRunDetail,
    SkillRunMetrics,
    SkillStageMetrics,
    SkillStepRun,
    SkillWorkflowStage,
    StyleBibleRevision,
    TimelineAudioItem,
    TimelineCaptionCue,
    TimelineV3Clip,
    TimelineV3Revision,
    TimelineV3Transition,
    ValidationStatus,
    content_digest,
    utc_now,
)


class WorkflowRepository(Protocol):
    async def list_projects(self) -> list[Project]: ...

    async def get_project(self, project_id: UUID) -> Project | None: ...

    async def get_skill_version_snapshot(self, project_id: UUID) -> SkillVersionSnapshot | None: ...

    async def save_brand_snapshot(self, item: BrandSnapshot) -> BrandSnapshot: ...

    async def get_brand_snapshot(self, item_id: UUID) -> BrandSnapshot | None: ...

    async def list_brand_snapshots(self, project_id: UUID) -> list[BrandSnapshot]: ...

    async def save_creative_brief_revision(
        self, item: CreativeBriefRevision
    ) -> CreativeBriefRevision: ...

    async def list_creative_brief_revisions(
        self, project_id: UUID
    ) -> list[CreativeBriefRevision]: ...

    async def replace_asset_usages(
        self, project_id: UUID, items: list[AssetUsage]
    ) -> list[AssetUsage]: ...

    async def list_asset_usages(self, project_id: UUID) -> list[AssetUsage]: ...

    async def replace_claim_evidence(
        self, project_id: UUID, items: list[ClaimEvidence]
    ) -> list[ClaimEvidence]: ...

    async def list_claim_evidence(self, project_id: UUID) -> list[ClaimEvidence]: ...

    async def save_run_contract_revision(
        self, item: RunContractRevision
    ) -> RunContractRevision: ...

    async def get_run_contract_revision(self, item_id: UUID) -> RunContractRevision | None: ...

    async def list_run_contract_revisions(self, project_id: UUID) -> list[RunContractRevision]: ...

    async def save_creative_treatment_revision(
        self, item: CreativeTreatmentRevision
    ) -> CreativeTreatmentRevision: ...

    async def list_creative_treatment_revisions(
        self, project_id: UUID
    ) -> list[CreativeTreatmentRevision]: ...

    async def save_style_bible_revision(self, item: StyleBibleRevision) -> StyleBibleRevision: ...

    async def get_style_bible_revision(self, item_id: UUID) -> StyleBibleRevision | None: ...

    async def list_style_bible_revisions(self, project_id: UUID) -> list[StyleBibleRevision]: ...

    async def save_look_test(self, item: LookTest) -> LookTest: ...

    async def list_look_tests(self, project_id: UUID) -> list[LookTest]: ...

    async def save_outline_revision(self, item: OutlineRevision) -> OutlineRevision: ...

    async def list_outline_revisions(self, project_id: UUID) -> list[OutlineRevision]: ...

    async def save_shot_manifest_revision(
        self, item: ShotManifestRevision
    ) -> ShotManifestRevision: ...

    async def list_shot_manifest_revisions(
        self, project_id: UUID
    ) -> list[ShotManifestRevision]: ...

    async def save_skill_run(self, item: SkillRun) -> SkillRun: ...

    async def get_skill_run(self, item_id: UUID) -> SkillRun | None: ...

    async def list_skill_runs(self, project_id: UUID) -> list[SkillRun]: ...

    async def save_skill_step_run(self, item: SkillStepRun) -> SkillStepRun: ...

    async def get_skill_step_run(self, item_id: UUID) -> SkillStepRun | None: ...

    async def list_skill_step_runs(self, skill_run_id: UUID) -> list[SkillStepRun]: ...

    async def save_gate_decision(self, item: GateDecision) -> GateDecision: ...

    async def list_gate_decisions(self, skill_run_id: UUID) -> list[GateDecision]: ...

    async def save_skill_artifact(self, item: Artifact) -> Artifact: ...

    async def get_skill_artifact(self, item_id: UUID) -> Artifact | None: ...

    async def list_skill_artifacts(self, project_id: UUID) -> list[Artifact]: ...

    async def save_artifact_dependency(self, item: ArtifactDependency) -> ArtifactDependency: ...

    async def list_artifact_dependencies(
        self, artifact_id: UUID | None = None
    ) -> list[ArtifactDependency]: ...

    async def save_production_seed(self, item): ...

    async def list_production_seeds(self, project_id: UUID): ...

    async def save_generation_run(self, item: GenerationRun) -> GenerationRun: ...

    async def get_generation_run(self, item_id: UUID) -> GenerationRun | None: ...

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]: ...

    async def get_production_project(self, project_id: UUID) -> ProductionProject | None: ...

    async def save_production_project(self, item: ProductionProject) -> ProductionProject: ...

    async def save_generation_candidate(self, item: GenerationCandidate) -> GenerationCandidate: ...

    async def get_generation_candidate(self, item_id: UUID) -> GenerationCandidate | None: ...

    async def get_shot_plan(self, item_id: UUID) -> ShotPlan | None: ...

    async def save_shot_plan(self, item: ShotPlan) -> ShotPlan: ...

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]: ...

    async def save_timeline_v3_revision(self, item: TimelineV3Revision) -> TimelineV3Revision: ...

    async def get_timeline_v3_revision(self, item_id: UUID) -> TimelineV3Revision | None: ...

    async def list_timeline_v3_revisions(self, project_id: UUID) -> list[TimelineV3Revision]: ...

    async def save_audio_asset(self, item: AudioAsset) -> AudioAsset: ...

    async def list_audio_assets(self, project_id: UUID) -> list[AudioAsset]: ...

    async def save_mix_revision(self, item: MixRevision) -> MixRevision: ...

    async def list_mix_revisions(self, project_id: UUID) -> list[MixRevision]: ...

    async def save_delivery_manifest(self, item: DeliveryManifest) -> DeliveryManifest: ...

    async def list_delivery_manifests(self, project_id: UUID) -> list[DeliveryManifest]: ...


class ProductionSeedConsumer(Protocol):
    async def create_project_from_seed(self, seed, **kwargs): ...

    async def get_project(self, project_id: UUID): ...

    async def list_shots(self, project_id: UUID): ...

    async def create_image_run(self, shot_plan_id: UUID, payload): ...

    async def create_video_run(self, shot_plan_id: UUID, payload): ...

    async def advance(self, project_id: UUID, payload): ...


class ProductionTimelineReader(Protocol):
    async def get_timeline(self, project_id: UUID) -> ProductionTimeline: ...

    async def resolve_background_audio(self, project_id: UUID) -> tuple[Path, str]: ...


class ProductionExportReader(Protocol):
    async def get_export(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob: ...


class SkillWorkflowServiceError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


def _fail(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> SkillWorkflowServiceError:
    return SkillWorkflowServiceError(
        status_code,
        code,
        message,
        retryable=retryable,
    )


def _latest(items: list[Any]) -> Any | None:
    return max(items, key=lambda item: item.revision_number, default=None)


def _unique_text(values: Any, *, limit: int = 50) -> list[str]:
    source = [values] if isinstance(values, str) else values or []
    return list(dict.fromkeys(str(value).strip() for value in source if str(value).strip()))[:limit]


def _category_profile_brand_payload(profile: CategoryProfileSnapshot) -> dict[str, Any]:
    description = "\n".join(
        value
        for value in (
            profile.brief,
            f"所属品类：{profile.category_name}",
            f"适用场景：{'、'.join(profile.scenes)}" if profile.scenes else "",
            f"视觉风格：{profile.visual_style}" if profile.visual_style else "",
        )
        if value
    )[:4000]
    return {
        "source_category_profile_id": profile.id,
        "name": profile.brand_name or profile.display_name,
        "description": description,
        "values": profile.selling_points,
        "voice": [],
        "visual_identity": {
            "source": "category_profile",
            "profile_display_name": profile.display_name,
            "profile_revision": profile.revision,
            "profile_fingerprint": profile.fingerprint,
            "category_name": profile.category_name,
            "visual_style": profile.visual_style or "",
            "audiences": profile.audiences,
            "selling_points": profile.selling_points,
            "scenes": profile.scenes,
            "forbidden_claims": profile.forbidden_claims,
        },
    }


def _stable_token(prefix: str, *parts: object) -> str:
    value = ":".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _linear_gain_to_db(value: float) -> float:
    if value <= 0:
        return -60
    return max(-60, min(12, 20 * math.log10(value)))


def _allocate_frames(total: int, ratios: list[float]) -> list[int]:
    if total < len(ratios):
        raise _fail(422, "duration_too_short", "目标时长不足以容纳 Skill 叙事段落")
    normalized_total = sum(ratios)
    raw = [total * value / normalized_total for value in ratios]
    base = [max(1, math.floor(value)) for value in raw]
    remainder = total - sum(base)
    fractions = sorted(
        range(len(raw)),
        key=lambda index: raw[index] - math.floor(raw[index]),
        reverse=True,
    )
    cursor = 0
    while remainder > 0:
        base[fractions[cursor % len(fractions)]] += 1
        remainder -= 1
        cursor += 1
    while remainder < 0:
        candidates = [index for index, value in enumerate(base) if value > 1]
        if not candidates:
            raise _fail(422, "duration_too_short", "目标时长不足")
        base[candidates[cursor % len(candidates)]] -= 1
        remainder += 1
        cursor += 1
    return base


class SkillWorkflowService:
    COMPILER_VERSION = "viraldna.skill-compiler/v1"
    LOOK_TEST_CONCURRENCY = 2
    LOOK_TEST_HEARTBEAT_SECONDS = 5
    LOOK_TEST_HARD_TIMEOUT_SECONDS = 600

    def __init__(
        self,
        repository: WorkflowRepository,
        projects: ProjectService,
        account_context: AccountContextService,
        *,
        category_profiles: CategoryProfileService | None = None,
        image_gateway: ImageGenerationGateway | None = None,
        production_service: ProductionSeedConsumer | None = None,
        timeline_reader: ProductionTimelineReader | None = None,
        export_reader: ProductionExportReader | None = None,
    ) -> None:
        self.repository = repository
        self.projects = projects
        self.account_context = account_context
        self.category_profiles = category_profiles
        self.image_gateway = image_gateway
        self.production_service = production_service
        self.timeline_reader = timeline_reader
        self.export_reader = export_reader
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._look_test_tasks: dict[UUID, asyncio.Task[LookTest]] = {}
        self._look_test_cancel_events: dict[UUID, dict[str, Event]] = {}

    def _lock(self, project_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(project_id, asyncio.Lock())

    async def workspace(self, project_id: UUID) -> SkillProjectWorkspace:
        project = await self._require_skill_project(project_id)
        brands = await self.repository.list_brand_snapshots(project.id)
        briefs = await self.repository.list_creative_brief_revisions(project.id)
        contracts = await self.repository.list_run_contract_revisions(project.id)
        treatments = await self.repository.list_creative_treatment_revisions(project.id)
        bibles = await self.repository.list_style_bible_revisions(project.id)
        look_tests = await self.repository.list_look_tests(project.id)
        outlines = await self.repository.list_outline_revisions(project.id)
        manifests = await self.repository.list_shot_manifest_revisions(project.id)
        runs = await self.repository.list_skill_runs(project.id)
        seeds = await self.repository.list_production_seeds(project.id)
        timelines = await self.repository.list_timeline_v3_revisions(project.id)
        mixes = await self.repository.list_mix_revisions(project.id)
        deliveries = await self.repository.list_delivery_manifests(project.id)
        run = max(runs, key=lambda item: item.updated_at, default=None)
        look_test = max(look_tests, key=lambda item: item.updated_at, default=None)
        if run is not None and look_test is not None:
            look_test = await self._repair_empty_succeeded_look_test(run, look_test)
        active_brief = _latest(briefs)
        active_bible = _latest(bibles)
        active_contract = (
            await self.repository.get_run_contract_revision(run.run_contract_revision_id)
            if run is not None
            else None
        )
        if (
            run is not None
            and look_test is not None
            and look_test.candidate_ids
            and active_brief is not None
            and active_bible is not None
            and active_contract is not None
        ):
            await self._repair_look_test_media_relations(
                run,
                project,
                look_test,
                active_brief,
                active_bible,
                active_contract,
            )
        timeline = _latest(timelines)
        mix = next(
            (item for item in mixes if timeline and item.id == timeline.mix_revision_id),
            None,
        )
        delivery = next(
            (
                item
                for item in reversed(deliveries)
                if timeline and item.timeline_revision_id == timeline.id
            ),
            None,
        )
        return SkillProjectWorkspace(
            brand_snapshot=max(brands, key=lambda item: item.created_at, default=None),
            brief=active_brief,
            asset_usages=await self.repository.list_asset_usages(project.id),
            claims=await self.repository.list_claim_evidence(project.id),
            run_contract=active_contract or _latest(contracts),
            treatment=_latest(treatments),
            style_bible=active_bible,
            look_test=look_test,
            outline=_latest(outlines),
            shot_manifest=_latest(manifests),
            run=(await self.run_detail(run.id) if run else None),
            production_seed_id=(seeds[-1].id if seeds else None),
            production_project_id=project.source_binding.production_project_id,
            timeline=timeline,
            audio_assets=await self.repository.list_audio_assets(project.id),
            mix_revision=mix,
            delivery_manifest=delivery,
        )

    async def create_brand_snapshot(
        self,
        project_id: UUID,
        payload: BrandSnapshotCreate,
    ) -> BrandSnapshot:
        project = await self._require_skill_project(project_id)
        if await self.repository.list_brand_snapshots(project.id):
            raise _fail(409, "brand_snapshot_exists", "品牌快照已创建；品牌变化请新建项目")
        source_profile = None
        payload_data = payload.model_dump(mode="python")
        if payload.source_category_profile_id is not None:
            if self.category_profiles is None:
                raise _fail(
                    503,
                    "category_profile_service_unavailable",
                    "品类库服务未启用，无法创建品牌快照",
                )
            try:
                source_profile = await self.category_profiles.snapshot(
                    payload.source_category_profile_id
                )
            except CategoryProfileServiceError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            payload_data = _category_profile_brand_payload(source_profile)
        material = {
            "id": uuid4(),
            "project_id": project.id,
            **payload_data,
            "created_at": utc_now(),
        }
        material["content_hash"] = content_digest(material)
        saved = await self.repository.save_brand_snapshot(BrandSnapshot.model_validate(material))
        if source_profile is not None and self.category_profiles is not None:
            await self.category_profiles.mark_used(source_profile.id)
        return saved

    async def put_brief(
        self,
        project_id: UUID,
        payload: CreativeBriefInput,
    ) -> CreativeBriefRevision:
        project = await self._require_skill_project(project_id)
        brand = await self.repository.get_brand_snapshot(payload.brand_snapshot_id)
        if brand is None or brand.project_id != project.id:
            raise _fail(404, "brand_snapshot_not_found", "品牌快照不存在")
        usages = await self.repository.list_asset_usages(project.id)
        usage_ids = {item.id for item in usages}
        if not set(payload.selected_asset_usage_ids).issubset(usage_ids):
            raise _fail(422, "asset_usage_invalid", "简报引用了不属于当前项目的素材用途")
        revisions = await self.repository.list_creative_brief_revisions(project.id)
        material = payload.model_dump(mode="python")
        item = CreativeBriefRevision(
            **material,
            project_id=project.id,
            revision_number=len(revisions) + 1,
            target_duration_frames=payload.target_duration_seconds * payload.fps,
            input_hash=content_digest(material),
            created_by=(await self.account_context.current_account()).id,
        )
        await self.repository.save_creative_brief_revision(item)
        if revisions:
            await self.mark_dependency_stale(
                DependencyImpactRequest(
                    depends_on_type="creative_brief",
                    depends_on_id=str(revisions[-1].id),
                    next_digest=item.input_hash,
                ),
                apply=True,
            )
            await self._invalidate_gates_from(
                project.id,
                SkillGate.BRIEF_APPROVED,
                "创作简报已更新",
            )
        await self.projects.bind_skill_run(
            project.id,
            stage=ProjectStage.CREATIVE_BRIEF,
            status=ProjectStatus.DRAFT,
        )
        return item

    async def replace_asset_usages(
        self,
        project_id: UUID,
        payload: list[AssetUsageInput],
    ) -> list[AssetUsage]:
        project = await self._require_skill_project(project_id)
        snapshot = await self._require_snapshot(project.id)
        role_specs = {item.role: item for item in snapshot.manifest.spec.intake.asset_roles}
        for item in payload:
            role = role_specs.get(item.role)
            if role is None:
                raise _fail(422, "asset_role_unknown", f"Skill 未声明素材角色：{item.role}")
            if item.fidelity.value != role.fidelity:
                raise _fail(
                    422,
                    "asset_fidelity_mismatch",
                    f"素材角色 {role.label} 必须使用 {role.fidelity} 忠实度",
                )
        now = utc_now()
        items = [
            AssetUsage(
                id=item.id or uuid4(),
                project_id=project.id,
                **item.model_dump(mode="python", exclude={"id"}),
                updated_at=now,
            )
            for item in payload
        ]
        if len({item.asset_id for item in items}) != len(items):
            raise _fail(422, "asset_usage_duplicate", "同一素材只能声明一个项目用途")
        previous = await self.repository.list_asset_usages(project.id)
        saved = await self.repository.replace_asset_usages(project.id, items)
        previous_by_id = {item.id: item for item in previous}
        for item in items:
            old = previous_by_id.get(item.id)
            if old and old.model_dump(mode="json") != item.model_dump(mode="json"):
                await self.mark_dependency_stale(
                    DependencyImpactRequest(
                        depends_on_type="asset_usage",
                        depends_on_id=str(item.id),
                        next_digest=content_digest(item, exclude={"updated_at"}),
                    ),
                    apply=True,
                )
        previous_material = [
            item.model_dump(mode="json", exclude={"updated_at"}) for item in previous
        ]
        saved_material = [item.model_dump(mode="json", exclude={"updated_at"}) for item in saved]
        if previous and content_digest(previous_material) != content_digest(saved_material):
            await self._invalidate_gates_from(
                project.id,
                SkillGate.BRIEF_APPROVED,
                "素材用途或授权已更新",
            )
        return saved

    async def replace_claims(
        self,
        project_id: UUID,
        payload: list[ClaimEvidenceInput],
    ) -> list[ClaimEvidence]:
        project = await self._require_skill_project(project_id)
        account = await self.account_context.current_account()
        now = utc_now()
        items = [
            ClaimEvidence(
                id=item.id or uuid4(),
                project_id=project.id,
                **item.model_dump(mode="python", exclude={"id"}),
                approved_by=(account.id if item.status == ClaimStatus.APPROVED else None),
                approved_at=(now if item.status == ClaimStatus.APPROVED else None),
                updated_at=now,
            )
            for item in payload
        ]
        previous = await self.repository.list_claim_evidence(project.id)
        saved = await self.repository.replace_claim_evidence(project.id, items)
        next_by_id = {item.id: item for item in saved}
        for old in previous:
            current = next_by_id.get(old.id)
            next_digest = content_digest(current) if current is not None else content_digest({})
            if current is None or content_digest(old) != next_digest:
                await self.mark_dependency_stale(
                    DependencyImpactRequest(
                        depends_on_type="claim_evidence",
                        depends_on_id=str(old.id),
                        next_digest=next_digest,
                    ),
                    apply=True,
                )
        previous_material = [
            item.model_dump(mode="json", exclude={"updated_at", "approved_at"}) for item in previous
        ]
        saved_material = [
            item.model_dump(mode="json", exclude={"updated_at", "approved_at"}) for item in saved
        ]
        if previous and content_digest(previous_material) != content_digest(saved_material):
            await self._invalidate_gates_from(
                project.id,
                SkillGate.BRIEF_APPROVED,
                "事实声明证据已更新",
            )
        return saved

    async def put_run_contract(
        self,
        project_id: UUID,
        payload: RunContractInput,
    ) -> RunContractRevision:
        project = await self._require_skill_project(project_id)
        if await self.repository.list_skill_runs(project.id):
            raise _fail(409, "run_contract_locked", "运行开始后不能更换模型或分辨率，请新建项目")
        revisions = await self.repository.list_run_contract_revisions(project.id)
        material = payload.model_dump(mode="python")
        item = RunContractRevision(
            **material,
            project_id=project.id,
            revision_number=len(revisions) + 1,
            input_hash=content_digest(material),
            created_by=(await self.account_context.current_account()).id,
        )
        await self.repository.save_run_contract_revision(item)
        if revisions:
            await self.mark_dependency_stale(
                DependencyImpactRequest(
                    depends_on_type="run_contract",
                    depends_on_id=str(revisions[-1].id),
                    next_digest=item.input_hash,
                ),
                apply=True,
            )
        return item

    async def preflight(self, project_id: UUID) -> PreflightResult:
        project = await self._require_skill_project(project_id)
        snapshot = await self._require_snapshot(project.id)
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        contract = _latest(await self.repository.list_run_contract_revisions(project.id))
        usages = await self.repository.list_asset_usages(project.id)
        claims = await self.repository.list_claim_evidence(project.id)
        issues: list[PreflightIssue] = []
        if brief is None:
            issues.append(
                PreflightIssue(
                    code="brief_required",
                    severity="error",
                    message="请先完成创作简报",
                )
            )
        if contract is None:
            issues.append(
                PreflightIssue(
                    code="run_contract_required",
                    severity="error",
                    message="必须主动选择图片和视频模型及分辨率",
                )
            )
        if brief is not None:
            usage_ids = {item.id for item in usages}
            if not set(brief.selected_asset_usage_ids).issubset(usage_ids):
                issues.append(
                    PreflightIssue(
                        code="brief_asset_usage_stale",
                        severity="error",
                        message="创作简报引用的素材用途已变化，请重新确认简报",
                    )
                )
            role_counts: dict[str, int] = {}
            for usage in usages:
                role_counts[usage.role] = role_counts.get(usage.role, 0) + 1
            # At project scope, asset roles only require enough available material.
            # Model input bounds apply to the subset selected for a concrete generation.
            for role in snapshot.manifest.spec.intake.asset_roles:
                count = role_counts.get(role.role, 0)
                if count < role.min_count:
                    issues.append(
                        PreflightIssue(
                            code="asset_role_required",
                            severity="error",
                            message=f"{role.label}至少需要 {role.min_count} 个素材",
                            entity_type="asset_role",
                            entity_id=role.role,
                        )
                    )
            for question in snapshot.manifest.spec.intake.questions:
                answer = brief.skill_answers.get(question.key)
                if question.required and (answer is None or answer == "" or answer == []):
                    issues.append(
                        PreflightIssue(
                            code="skill_answer_required",
                            severity="error",
                            message=f"请回答：{question.label}",
                            entity_type="skill_question",
                            entity_id=question.key,
                        )
                    )
            public_delivery = brief.distribution_channel not in {"internal", "内部"}
            for usage in usages:
                if public_delivery and usage.rights_status in {
                    RightsStatus.UNKNOWN,
                    RightsStatus.EXPIRED,
                }:
                    issues.append(
                        PreflightIssue(
                            code="asset_rights_blocked",
                            severity="error",
                            message="公开交付前必须确认素材权利",
                            entity_type="asset_usage",
                            entity_id=str(usage.id),
                        )
                    )
                if (
                    public_delivery
                    and usage.allowed_distribution
                    and brief.distribution_channel not in usage.allowed_distribution
                ):
                    issues.append(
                        PreflightIssue(
                            code="asset_distribution_forbidden",
                            severity="error",
                            message="素材授权不包含当前分发渠道",
                            entity_type="asset_usage",
                            entity_id=str(usage.id),
                        )
                    )
        if contract is not None:
            if contract.audio_source_strategy == "source":
                issues.append(
                    PreflightIssue(
                        code="skill_source_audio_unavailable",
                        severity="error",
                        message="Skill 项目没有原视频音轨，请选择候选音频或静音",
                    )
                )
            # Project assets are an availability pool, not one model request. Reference
            # mode and capacity are validated later against each shot's explicit inputs.
            try:
                image_model = load_image_model_catalog().option(contract.image_model_id)
                image_capability = image_model.capabilities
                if image_model.provider != contract.image_provider_connection_id:
                    issues.append(
                        PreflightIssue(
                            code="image_provider_contract_mismatch",
                            severity="error",
                            message="图片模型与项目锁定的 Provider 不一致，请重新选择模型",
                        )
                    )
                if (
                    contract.image_width > image_capability.maximum_width
                    or contract.image_height > image_capability.maximum_height
                    or contract.image_width * contract.image_height
                    > image_capability.maximum_pixels
                ):
                    issues.append(
                        PreflightIssue(
                            code="image_resolution_unsupported",
                            severity="error",
                            message="所选图片模型不支持当前图片分辨率",
                        )
                    )
            except ImageModelCatalogError as exc:
                issues.append(
                    PreflightIssue(
                        code="image_model_unavailable",
                        severity="error",
                        message=str(exc),
                    )
                )
            try:
                video_model = load_video_model_catalog().option(contract.video_model_id)
                video_capability = video_model.capability
                if contract.video_resolution_label not in video_capability.supported_resolutions:
                    issues.append(
                        PreflightIssue(
                            code="video_resolution_unsupported",
                            severity="error",
                            message="所选视频模型不支持当前视频分辨率",
                        )
                    )
                if (
                    brief is not None
                    and video_capability.supported_aspect_ratios
                    and brief.output_aspect_ratio not in video_capability.supported_aspect_ratios
                ):
                    issues.append(
                        PreflightIssue(
                            code="video_aspect_ratio_unsupported",
                            severity="error",
                            message="所选视频模型不支持当前画幅",
                        )
                    )
                if contract.generate_video_audio and not video_capability.native_audio:
                    issues.append(
                        PreflightIssue(
                            code="video_native_audio_unsupported",
                            severity="error",
                            message="所选视频模型不能生成新音频",
                        )
                    )
            except VideoModelCatalogError as exc:
                issues.append(
                    PreflightIssue(
                        code="video_model_unavailable",
                        severity="error",
                        message=str(exc),
                    )
                )
            if any(item.fidelity == Fidelity.EXACT for item in usages) and not (
                contract.supports_exact_overlay
            ):
                issues.append(
                    PreflightIssue(
                        code="exact_overlay_unsupported",
                        severity="error",
                        message="当前执行配置不支持 Logo 等 exact 素材的确定性合成",
                    )
                )
            if contract.estimate_status != "known":
                issues.append(
                    PreflightIssue(
                        code="cost_estimate_unknown",
                        severity="error",
                        message="成本尚未完整估算，不能开始付费生成",
                    )
                )
            if (
                contract.budget_limit_micros is not None
                and contract.estimated_cost_micros > contract.budget_limit_micros
            ):
                issues.append(
                    PreflightIssue(
                        code="budget_exceeded",
                        severity="error",
                        message="预计成本超过预算上限",
                    )
                )
        for claim in claims:
            if claim.status in {ClaimStatus.UNVERIFIED, ClaimStatus.FORBIDDEN}:
                issues.append(
                    PreflightIssue(
                        code="claim_unapproved",
                        severity="error",
                        message="存在未经验证或禁止使用的事实声明",
                        entity_type="claim_evidence",
                        entity_id=str(claim.id),
                    )
                )
        return PreflightResult(
            project_id=project.id,
            can_start=not any(item.severity == "error" for item in issues),
            issues=issues,
            estimated_cost_micros=contract.estimated_cost_micros if contract else 0,
            budget_limit_micros=contract.budget_limit_micros if contract else None,
        )

    async def start_run(self, project_id: UUID, payload: SkillRunCreate) -> SkillRunDetail:
        project = await self._require_skill_project(project_id)
        snapshot = await self._require_snapshot(project.id)
        contract = await self.repository.get_run_contract_revision(payload.run_contract_revision_id)
        if contract is None or contract.project_id != project.id:
            raise _fail(404, "run_contract_not_found", "运行契约不存在")
        latest_contract = _latest(await self.repository.list_run_contract_revisions(project.id))
        if latest_contract is None or latest_contract.id != contract.id:
            raise _fail(409, "run_contract_stale", "只能使用当前最新运行契约开始项目")
        existing = await self.repository.list_skill_runs(project.id)
        if payload.idempotency_key:
            match = next(
                (item for item in existing if item.idempotency_key == payload.idempotency_key),
                None,
            )
            if match is not None:
                return await self.run_detail(match.id)
        check = await self.preflight(project.id)
        if not check.can_start:
            raise _fail(409, "preflight_blocked", "运行预检未通过")
        run = SkillRun(
            project_id=project.id,
            skill_version_snapshot_id=snapshot.id,
            run_contract_revision_id=contract.id,
            execution_status=ExecutionStatus.RUNNING,
            estimated_cost_micros=contract.estimated_cost_micros,
            idempotency_key=payload.idempotency_key,
            started_at=utc_now(),
        )
        await self.repository.save_skill_run(run)
        await self.projects.bind_skill_run(
            project.id,
            skill_run_id=run.id,
            status=ProjectStatus.RUNNING,
        )
        return await self.run_detail(run.id)

    async def compile_style(self, run_id: UUID) -> SkillRunDetail:
        run, project = await self._require_run(run_id)
        gates = await self.repository.list_gate_decisions(run.id)
        if not self._gate_is_approved(gates, SkillGate.BRIEF_APPROVED):
            raise _fail(409, "brief_gate_required", "请先人工批准创作简报")
        await self._assert_budget(run)
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        brand = (
            await self.repository.get_brand_snapshot(brief.brand_snapshot_id)
            if brief is not None
            else None
        )
        snapshot = await self._require_snapshot(project.id)
        contract = await self.repository.get_run_contract_revision(run.run_contract_revision_id)
        if brief is None or brand is None or contract is None:
            raise _fail(409, "style_inputs_missing", "风格编译缺少简报、品牌或运行契约")
        step, reused = await self._begin_step(
            run,
            SkillWorkflowStage.STYLE_CONFIRMATION,
            "compile_style_bible",
            content_digest(
                {
                    "brief": brief.input_hash,
                    "brand": brand.content_hash,
                    "skill": snapshot.content_digest,
                    "compiler": self.COMPILER_VERSION,
                }
            ),
        )
        if reused:
            return await self.run_detail(run.id)
        started = time.perf_counter()
        spec = snapshot.manifest.spec
        brand_identity = brand.visual_identity if isinstance(brand.visual_identity, dict) else {}
        profile_visual_style = str(brand_identity.get("visual_style", "")).strip()
        profile_category = str(brand_identity.get("category_name", "")).strip()
        profile_scenes = _unique_text(brand_identity.get("scenes", []), limit=16)
        profile_positioning = next(
            (line.strip() for line in brand.description.splitlines() if line.strip()),
            "",
        )
        profile_locks = _unique_text(
            [
                f"品牌与品类：{brand.name} / {profile_category}"
                if profile_category
                else f"品牌识别：{brand.name}",
                f"品牌定位：{profile_positioning}" if profile_positioning else "",
                f"品牌视觉风格：{profile_visual_style}" if profile_visual_style else "",
            ]
        )
        visual_keywords = _unique_text(
            [*spec.style.visual_keywords, profile_visual_style],
        )
        positive_locks = _unique_text([*spec.style.positive_lock, *profile_locks])
        negative_locks = _unique_text([*spec.style.negative_lock, *brief.forbidden_messages])
        treatment_payload = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(
                await self.repository.list_creative_treatment_revisions(project.id)
            )
            + 1,
            "core_idea": f"以“{brief.objective}”为核心，让 {brief.audience} 在首屏理解价值。",
            "narrative_structure": " → ".join(item.key for item in spec.narrative.outline_pattern),
            "opening_hook": spec.narrative.outline_pattern[0].purpose,
            "rhythm_curve": [item.purpose for item in spec.narrative.outline_pattern],
            "visual_approach": "、".join(visual_keywords),
            "presentation_principles": [
                "品牌识别优先",
                "品类档案与用户创作目标共同约束内容",
                "事实声明只使用已批准证据",
                "exact 素材留给确定性合成",
            ],
            "sound_direction": str(spec.audio.get("direction", "全片声音保持一致")),
            "call_to_action": brief.call_to_action,
            "risks": ["生成画面需人工审核品牌和人物一致性"],
            "source_input_hash": step.input_hash,
            "created_at": utc_now(),
        }
        treatment_payload["content_hash"] = content_digest(treatment_payload)
        treatment = CreativeTreatmentRevision.model_validate(treatment_payload)
        bible_payload = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(await self.repository.list_style_bible_revisions(project.id))
            + 1,
            "skill_version_digest": snapshot.content_digest,
            "brand_snapshot_digest": brand.content_hash,
            "brief_revision_id": brief.id,
            "reference_fact_digests": [
                item.snapshot_sha256 for item in await self.repository.list_asset_usages(project.id)
            ],
            "palette": spec.style.palette_policy,
            "typography": spec.style.typography,
            "lighting": spec.style.lighting,
            "composition": spec.style.composition,
            "camera": spec.style.camera,
            "motion": {"policy": spec.style.camera.get("motion", [])},
            "texture": {
                "keywords": visual_keywords,
                "category_scenes": profile_scenes,
            },
            "rhythm": spec.style.rhythm,
            "product_identity_lock": ["产品外形、包装结构和品牌识别不得漂移"],
            "character_identity_lock": ["同一角色的可识别身份必须跨镜头一致"],
            "positive_lock": positive_locks,
            "negative_lock": negative_locks,
            "image_prompt_rules": spec.prompt_rules.image_sections,
            "video_prompt_rules": spec.prompt_rules.video_sections,
            "validation_checklist": [
                "画幅与 Run Contract 一致",
                "图片提示词不包含时间动作过程",
                "视频提示词绑定已采用图片摘要",
                "系统校验不等同于人工批准",
            ],
            "input_hash": step.input_hash,
            "created_at": utc_now(),
        }
        bible_payload["content_hash"] = content_digest(bible_payload)
        bible = StyleBibleRevision.model_validate(bible_payload)
        await self.repository.save_creative_treatment_revision(treatment)
        await self.repository.save_style_bible_revision(bible)
        artifact = await self._save_structured_artifact(
            project.id,
            step.id,
            "style_bible",
            bible.model_dump(mode="json"),
            step.input_hash,
            len(await self.repository.list_style_bible_revisions(project.id)),
        )
        await self._save_dependencies(
            artifact,
            [
                ("creative_brief", str(brief.id), brief.input_hash),
                ("brand_snapshot", str(brand.id), brand.content_hash),
                ("skill_version", str(snapshot.id), snapshot.content_digest),
                ("run_contract", str(contract.id), contract.input_hash),
            ],
        )
        representative_shot_keys = [
            _stable_token("shot", project.id, bible.id, "hero"),
            _stable_token("shot", project.id, bible.id, "complex"),
        ][: spec.workflow.look_test.representative_count]
        look_candidate_count = contract.candidate_count_by_stage.get("look_test", 1)
        look = LookTest(
            project_id=project.id,
            style_bible_revision_id=bible.id,
            representative_shot_keys=representative_shot_keys,
            run_contract_revision_id=contract.id,
            items=[
                LookTestItem(
                    shot_key=shot_key,
                    requested_candidate_count=look_candidate_count,
                )
                for shot_key in representative_shot_keys
            ],
            output_width=contract.image_width,
            output_height=contract.image_height,
        )
        await self.repository.save_look_test(look)
        await self._finish_step(step, [artifact.id], started=started)
        await self.projects.bind_skill_run(project.id, stage=ProjectStage.STYLE_CONFIRMATION)
        return await self.run_detail(run.id)

    async def start_look_test_generation(self, run_id: UUID) -> LookTest:
        """Start durable Look Test work and return immediately for progress polling."""

        if self.image_gateway is None:
            raise _fail(503, "image_gateway_unavailable", "图片生成服务未启用")
        run, project = await self._require_run(run_id)
        async with self._lock(project.id):
            active = self._look_test_tasks.get(run.id)
            if active is not None and not active.done():
                return await self._latest_look_test(project.id)
            prepared = await self._prepare_look_test_generation(run, project)
            if prepared is None:
                return await self._latest_look_test(project.id)
            task = asyncio.create_task(self._execute_look_test(*prepared))
            self._look_test_tasks[run.id] = task

            def clear_finished(finished: asyncio.Task[LookTest]) -> None:
                self._look_test_tasks.pop(run.id, None)
                self._look_test_cancel_events.pop(run.id, None)
                try:
                    finished.exception()
                except (asyncio.CancelledError, Exception):
                    pass

            task.add_done_callback(clear_finished)
            return prepared[2]

    async def generate_look_test(self, run_id: UUID) -> LookTest:
        """Compatibility entry point that waits for the durable background operation."""

        started = await self.start_look_test_generation(run_id)
        task = self._look_test_tasks.get(run_id)
        if task is not None:
            return await asyncio.shield(task)
        latest = await self.repository.list_look_tests(started.project_id)
        return max(latest, key=lambda item: item.updated_at, default=started)

    async def cancel_look_test_generation(self, run_id: UUID) -> LookTest:
        run, project = await self._require_run(run_id)
        for event in self._look_test_cancel_events.get(run.id, {}).values():
            event.set()
        task = self._look_test_tasks.get(run.id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        look = await self._latest_look_test(project.id)
        if look.execution_status == ExecutionStatus.RUNNING:
            now = utc_now()
            items = [
                item.model_copy(
                    update={
                        "execution_status": ExecutionStatus.CANCELLED,
                        "progress": 0,
                        "completed_at": now,
                        "last_heartbeat_at": now,
                        "error_code": "look_test_cancelled",
                        "error_message": "用户停止了等待",
                        "retryable": True,
                    }
                )
                if item.execution_status in {ExecutionStatus.PENDING, ExecutionStatus.RUNNING}
                else item
                for item in look.items
            ]
            look = look.model_copy(
                update={
                    "items": items,
                    "execution_status": ExecutionStatus.CANCELLED,
                    "completed_at": now,
                    "last_heartbeat_at": now,
                    "error_message": "生成已停止；已完成图片会保留，可继续生成未完成项。",
                    "updated_at": now,
                }
            )
            await self.repository.save_look_test(look)
        return look

    async def _latest_look_test(self, project_id: UUID) -> LookTest:
        look = max(
            await self.repository.list_look_tests(project_id),
            key=lambda item: item.updated_at,
            default=None,
        )
        if look is None:
            raise _fail(409, "look_test_inputs_missing", "请先完成风格编译")
        return look

    async def _prepare_look_test_generation(self, run: SkillRun, project: Project):
        look = await self._latest_look_test(project.id)
        look = await self._repair_empty_succeeded_look_test(run, look)
        bible = await self.repository.get_style_bible_revision(look.style_bible_revision_id)
        contract = await self.repository.get_run_contract_revision(run.run_contract_revision_id)
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        if bible is None or contract is None or brief is None:
            raise _fail(409, "look_test_inputs_missing", "请先完成风格编译")
        if look.execution_status == ExecutionStatus.SUCCEEDED and look.candidate_ids:
            return None
        await self._assert_budget(run)

        # A live in-process task is handled by start_look_test_generation. Reaching this
        # branch with RUNNING means the worker disappeared, so release the stale lock.
        if look.execution_status == ExecutionStatus.RUNNING:
            now = utc_now()
            for old_step in reversed(await self.repository.list_skill_step_runs(run.id)):
                if (
                    old_step.operation == "generate_look_test"
                    and old_step.execution_status == ExecutionStatus.RUNNING
                ):
                    await self.repository.save_skill_step_run(
                        old_step.model_copy(
                            update={
                                "execution_status": ExecutionStatus.FAILED,
                                "error_code": "worker_interrupted",
                                "error_message": (
                                    "Look Test worker was interrupted; "
                                    "completed images were preserved."
                                ),
                                "retryable": True,
                                "completed_at": now,
                                "last_heartbeat_at": now,
                            }
                        )
                    )
                    break

        step, reused = await self._begin_step(
            run,
            SkillWorkflowStage.STYLE_CONFIRMATION,
            "generate_look_test",
            content_digest(
                {
                    "style": bible.content_hash,
                    "model": contract.image_model_id,
                    "provider": contract.image_provider_connection_id,
                    "width": contract.image_width,
                    "height": contract.image_height,
                }
            ),
        )
        if reused:
            return None

        existing_by_key = {item.shot_key: item for item in look.items}
        candidate_count = contract.candidate_count_by_stage.get("look_test", 1)
        items: list[LookTestItem] = []
        for shot_key in look.representative_shot_keys:
            existing = existing_by_key.get(shot_key)
            if existing is not None and existing.execution_status == ExecutionStatus.SUCCEEDED:
                items.append(existing)
            else:
                items.append(
                    (existing or LookTestItem(shot_key=shot_key)).model_copy(
                        update={
                            "requested_candidate_count": candidate_count,
                            "execution_status": ExecutionStatus.PENDING,
                            "progress": 0,
                            "completed_at": None,
                            "error_code": None,
                            "error_message": None,
                            "retryable": False,
                        }
                    )
                )
        now = utc_now()
        completed_count = sum(item.execution_status == ExecutionStatus.SUCCEEDED for item in items)
        prepared_look = look.model_copy(
            update={
                "items": items,
                "candidate_ids": [
                    candidate_id for item in items for candidate_id in item.candidate_ids
                ],
                "selected_candidate_ids": [
                    candidate_id
                    for candidate_id in look.selected_candidate_ids
                    if any(candidate_id in item.candidate_ids for item in items)
                ],
                "execution_status": ExecutionStatus.RUNNING,
                "progress": round(completed_count * 100 / max(1, len(items))),
                "validation_status": ValidationStatus.UNCHECKED,
                "provider": contract.image_provider_connection_id,
                "model": contract.image_model_id,
                "started_at": now,
                "completed_at": None,
                "last_heartbeat_at": now,
                "error_message": None,
                "updated_at": now,
            }
        )
        await self.repository.save_look_test(prepared_look)
        return run, project, prepared_look, bible, contract, brief, step

    async def _repair_empty_succeeded_look_test(
        self,
        run: SkillRun,
        look: LookTest,
    ) -> LookTest:
        """Release legacy false-success state when no image candidate exists."""

        if look.execution_status != ExecutionStatus.SUCCEEDED or look.candidate_ids:
            return look
        contract = await self.repository.get_run_contract_revision(look.run_contract_revision_id)
        candidate_count = contract.candidate_count_by_stage.get("look_test", 1) if contract else 1
        now = utc_now()
        items = [
            LookTestItem(
                shot_key=shot_key,
                requested_candidate_count=candidate_count,
                execution_status=ExecutionStatus.FAILED,
                completed_at=now,
                last_heartbeat_at=now,
                error_code="look_test_empty_result",
                error_message="上一轮未生成有效图片",
                retryable=True,
            )
            for shot_key in look.representative_shot_keys
        ]
        repaired = look.model_copy(
            update={
                "items": items,
                "execution_status": ExecutionStatus.FAILED,
                "progress": 0,
                "validation_status": ValidationStatus.UNCHECKED,
                "review_status": ReviewStatus.UNREVIEWED,
                "selected_candidate_ids": [],
                "completed_at": now,
                "last_heartbeat_at": now,
                "error_message": "上一轮没有生成有效图片，可重新生成。",
                "updated_at": now,
            }
        )
        await self.repository.save_look_test(repaired)

        for step in reversed(await self.repository.list_skill_step_runs(run.id)):
            if (
                step.operation == "generate_look_test"
                and step.execution_status == ExecutionStatus.SUCCEEDED
            ):
                await self.repository.save_skill_step_run(
                    step.model_copy(
                        update={
                            "execution_status": ExecutionStatus.FAILED,
                            "progress": 0,
                            "error_code": "look_test_empty_result",
                            "error_message": "生成步骤未返回任何有效图片",
                            "retryable": True,
                            "completed_at": now,
                            "last_heartbeat_at": now,
                        }
                    )
                )
                break
        return repaired

    @staticmethod
    def _look_test_project(
        project: Project,
        run: SkillRun,
        bible: StyleBibleRevision,
        contract: RunContractRevision,
        brief: CreativeBriefRevision,
        *,
        project_id: UUID | None = None,
    ) -> ProductionProject:
        production_project_id = project_id or uuid4()
        return ProductionProject(
            id=production_project_id,
            record_id=project.id,
            owner_project_id=project.id,
            origin_type=ProductionOriginType.SKILL_RUN,
            origin_id=run.id,
            production_seed_id=uuid5(
                NAMESPACE_URL,
                f"viraldna:look-test:{project.id}:{production_project_id}",
            ),
            style_bible_revision_id=bible.id,
            timing_fps=contract.video_fps,
            name=f"{project.name} Look Test",
            output_aspect_ratio=brief.output_aspect_ratio,
            output_width=contract.image_width,
            output_height=contract.image_height,
            budget_limit_micros=contract.budget_limit_micros,
        )

    @staticmethod
    def _look_test_plan(
        project: ProductionProject,
        bible: StyleBibleRevision,
        contract: RunContractRevision,
        brief: CreativeBriefRevision,
        item: LookTestItem,
        index: int,
        *,
        plan_id: UUID | None = None,
    ) -> ShotPlan:
        prompt = (
            f"{brief.objective}。代表性视觉测试 {index}。"
            f"风格：{'、'.join(bible.positive_lock)}；"
            f"构图：{bible.composition}；光线：{bible.lighting}。"
        )
        return ShotPlan(
            id=plan_id or uuid4(),
            project_id=project.id,
            revision_id=bible.id,
            source_shot_id=item.shot_key,
            stable_shot_key=item.shot_key,
            index=index,
            order=index,
            timing_fps=contract.video_fps,
            start_frame=(index - 1) * contract.video_fps * 3,
            duration_frames=contract.video_fps * 3,
            source_kind=ShotSourceKind.SKILL_GENERATED,
            source_keyframe_origin="skill",
            start_seconds=float((index - 1) * 3),
            end_seconds=float(index * 3),
            duration_seconds=3,
            image_prompt=prompt,
            image_negative_constraints=bible.negative_lock,
            image_status=WorkflowItemStatus.READY,
            visual_beats=[
                ShotVisualBeat(
                    index=1,
                    source_origin="skill",
                    image_prompt=prompt,
                    image_negative_constraints=bible.negative_lock,
                    image_status=WorkflowItemStatus.READY,
                )
            ],
        )

    async def _repair_look_test_media_relations(
        self,
        skill_run: SkillRun,
        project: Project,
        look: LookTest,
        brief: CreativeBriefRevision,
        bible: StyleBibleRevision,
        contract: RunContractRevision,
    ) -> None:
        """Restore media ownership records required by candidate content routes."""

        candidates: list[GenerationCandidate] = []
        generation_runs: dict[UUID, GenerationRun] = {}
        for candidate_id in look.candidate_ids:
            candidate = await self.repository.get_generation_candidate(candidate_id)
            if candidate is None:
                continue
            candidates.append(candidate)
            generation_run = await self.repository.get_generation_run(candidate.generation_run_id)
            if generation_run is not None:
                generation_runs[generation_run.id] = generation_run

        candidate_ids_by_run: dict[UUID, set[UUID]] = {}
        for candidate in candidates:
            candidate_ids_by_run.setdefault(candidate.generation_run_id, set()).add(candidate.id)
        item_indexes = {item.shot_key: index for index, item in enumerate(look.items, 1)}
        for generation_run in generation_runs.values():
            production_project = await self.repository.get_production_project(
                generation_run.project_id
            )
            if production_project is None:
                production_project = self._look_test_project(
                    project,
                    skill_run,
                    bible,
                    contract,
                    brief,
                    project_id=generation_run.project_id,
                )
                await self.repository.save_production_project(production_project)

            if await self.repository.get_shot_plan(generation_run.shot_plan_id) is not None:
                continue
            run_candidate_ids = candidate_ids_by_run.get(generation_run.id, set())
            item = next(
                (
                    candidate_item
                    for candidate_item in look.items
                    if candidate_item.generation_run_id == generation_run.id
                    or bool(set(candidate_item.candidate_ids) & run_candidate_ids)
                ),
                None,
            )
            if item is None:
                continue
            plan = self._look_test_plan(
                production_project,
                bible,
                contract,
                brief,
                item,
                item_indexes.get(item.shot_key, 1),
                plan_id=generation_run.shot_plan_id,
            )
            await self.repository.save_shot_plan(plan)

    async def _execute_look_test(
        self,
        run: SkillRun,
        project: Project,
        look: LookTest,
        bible: StyleBibleRevision,
        contract: RunContractRevision,
        brief: CreativeBriefRevision,
        step: SkillStepRun,
    ) -> LookTest:
        started = time.perf_counter()
        transient_project = self._look_test_project(
            project,
            run,
            bible,
            contract,
            brief,
        )
        await self.repository.save_production_project(transient_project)
        current_look = look
        current_step = step
        state_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(self.LOOK_TEST_CONCURRENCY)
        cancel_events = {
            item.shot_key: Event()
            for item in look.items
            if item.execution_status != ExecutionStatus.SUCCEEDED
        }
        self._look_test_cancel_events[run.id] = cancel_events
        metrics = {"provider_ms": 0, "estimated": 0, "actual": 0}

        async def update_item(shot_key: str, **updates: Any) -> None:
            nonlocal current_look, current_step
            async with state_lock:
                now = utc_now()
                items = [
                    item.model_copy(update=updates) if item.shot_key == shot_key else item
                    for item in current_look.items
                ]
                succeeded = sum(
                    item.execution_status == ExecutionStatus.SUCCEEDED for item in items
                )
                candidate_ids = [
                    candidate_id for item in items for candidate_id in item.candidate_ids
                ]
                current_look = current_look.model_copy(
                    update={
                        "items": items,
                        "candidate_ids": candidate_ids,
                        "progress": round(succeeded * 100 / max(1, len(items))),
                        "last_heartbeat_at": now,
                        "updated_at": now,
                    }
                )
                await self.repository.save_look_test(current_look)
                current_step = current_step.model_copy(
                    update={
                        "progress": current_look.progress,
                        "provider_ms": metrics["provider_ms"],
                        "estimated_cost_micros": metrics["estimated"],
                        "actual_cost_micros": metrics["actual"],
                        "total_ms": max(0, round((time.perf_counter() - started) * 1000)),
                        "last_heartbeat_at": now,
                    }
                )
                await self.repository.save_skill_step_run(current_step)

        async def heartbeat() -> None:
            nonlocal current_look, current_step
            while True:
                await asyncio.sleep(self.LOOK_TEST_HEARTBEAT_SECONDS)
                async with state_lock:
                    now = utc_now()
                    current_look = current_look.model_copy(
                        update={
                            "items": [
                                item.model_copy(update={"last_heartbeat_at": now})
                                if item.execution_status == ExecutionStatus.RUNNING
                                else item
                                for item in current_look.items
                            ],
                            "last_heartbeat_at": now,
                            "updated_at": now,
                        }
                    )
                    await self.repository.save_look_test(current_look)
                    current_step = current_step.model_copy(
                        update={
                            "total_ms": max(0, round((time.perf_counter() - started) * 1000)),
                            "last_heartbeat_at": now,
                        }
                    )
                    await self.repository.save_skill_step_run(current_step)

        async def run_item(item: LookTestItem, index: int) -> None:
            nonlocal run
            if item.execution_status == ExecutionStatus.SUCCEEDED:
                return
            async with semaphore:
                cancel_event = cancel_events[item.shot_key]
                if cancel_event.is_set():
                    return
                generation_run_id = item.generation_run_id or uuid4()
                await update_item(
                    item.shot_key,
                    generation_run_id=generation_run_id,
                    execution_status=ExecutionStatus.RUNNING,
                    progress=0,
                    attempt=item.attempt + 1,
                    started_at=utc_now(),
                    completed_at=None,
                    last_heartbeat_at=utc_now(),
                    error_code=None,
                    error_message=None,
                    retryable=False,
                )
                plan = self._look_test_plan(
                    transient_project,
                    bible,
                    contract,
                    brief,
                    item,
                    index,
                )
                await self.repository.save_shot_plan(plan)
                try:
                    generation_run, candidates = await asyncio.wait_for(
                        self.image_gateway.generate(
                            transient_project,
                            plan,
                            bible.id,
                            [],
                            [],
                            candidate_count=item.requested_candidate_count,
                            source_path=None,
                            input_mode=ImageGenerationInputMode.TEXT_TO_IMAGE,
                            execution_mode=(
                                ImageExecutionMode.LOCAL_TOOL
                                if contract.image_provider_connection_id == "local_tool"
                                else ImageExecutionMode.REMOTE_API
                            ),
                            model_alias=contract.image_model_id,
                            reuse_cache=True,
                            run_id=generation_run_id,
                            cancel_event=cancel_event,
                        ),
                        timeout=self.LOOK_TEST_HARD_TIMEOUT_SECONDS,
                    )
                    await self.repository.save_generation_run(generation_run)
                    metrics["provider_ms"] += generation_run.latency_ms or 0
                    metrics["estimated"] += generation_run.estimated_cost_micros
                    metrics["actual"] += generation_run.actual_cost_micros
                    if (
                        generation_run.status
                        not in {
                            ProductionRunStatus.COMPLETED,
                            ProductionRunStatus.CACHED,
                        }
                        or not candidates
                    ):
                        await update_item(
                            item.shot_key,
                            execution_status=(
                                ExecutionStatus.CANCELLED
                                if generation_run.error_code == "generation_cancelled"
                                else (
                                    ExecutionStatus.BLOCKED
                                    if generation_run.provider_request_id
                                    else ExecutionStatus.FAILED
                                )
                            ),
                            progress=0,
                            provider=generation_run.provider,
                            model=generation_run.model,
                            request_id=generation_run.provider_request_id,
                            completed_at=utc_now(),
                            last_heartbeat_at=utc_now(),
                            error_code=generation_run.error_code or "look_test_generation_failed",
                            error_message=generation_run.error_message or "图片生成未返回候选",
                            retryable=(
                                generation_run.error_retryable
                                or not bool(generation_run.provider_request_id)
                            ),
                        )
                        return
                    for candidate in candidates:
                        await self.repository.save_generation_candidate(candidate)
                    async with state_lock:
                        latest_run = await self.repository.get_skill_run(run.id) or run
                        provider_request_ids = dict(latest_run.provider_request_ids)
                        if generation_run.provider_request_id:
                            provider_request_ids[f"look_test:{item.shot_key}"] = (
                                generation_run.provider_request_id
                            )
                        run = latest_run.model_copy(
                            update={
                                "actual_cost_micros": latest_run.actual_cost_micros
                                + generation_run.actual_cost_micros,
                                "provider_request_ids": provider_request_ids,
                                "updated_at": utc_now(),
                            }
                        )
                        await self.repository.save_skill_run(run)
                    await update_item(
                        item.shot_key,
                        candidate_ids=[candidate.id for candidate in candidates],
                        execution_status=ExecutionStatus.SUCCEEDED,
                        progress=100,
                        provider=generation_run.provider,
                        model=generation_run.model,
                        request_id=generation_run.provider_request_id,
                        completed_at=utc_now(),
                        last_heartbeat_at=utc_now(),
                        error_code=None,
                        error_message=None,
                        retryable=False,
                    )
                except TimeoutError:
                    cancel_event.set()
                    await update_item(
                        item.shot_key,
                        execution_status=ExecutionStatus.FAILED,
                        progress=0,
                        completed_at=utc_now(),
                        last_heartbeat_at=utc_now(),
                        error_code="look_test_timeout",
                        error_message="单张 Look Test 超过 10 分钟，已停止等待。",
                        retryable=True,
                    )
                except ImageGenerationGatewayError as exc:
                    await update_item(
                        item.shot_key,
                        execution_status=ExecutionStatus.FAILED,
                        progress=0,
                        completed_at=utc_now(),
                        last_heartbeat_at=utc_now(),
                        error_code=exc.code,
                        error_message=str(exc),
                        retryable=exc.retryable,
                    )
                except asyncio.CancelledError:
                    cancel_event.set()
                    await update_item(
                        item.shot_key,
                        execution_status=ExecutionStatus.CANCELLED,
                        progress=0,
                        completed_at=utc_now(),
                        last_heartbeat_at=utc_now(),
                        error_code="look_test_cancelled",
                        error_message="用户停止了等待",
                        retryable=True,
                    )
                    raise
                except Exception as exc:
                    await update_item(
                        item.shot_key,
                        execution_status=ExecutionStatus.FAILED,
                        progress=0,
                        completed_at=utc_now(),
                        last_heartbeat_at=utc_now(),
                        error_code="look_test_item_failed",
                        error_message=str(exc),
                        retryable=True,
                    )

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await asyncio.gather(
                *[
                    run_item(item, index)
                    for index, item in enumerate(look.items, start=1)
                    if item.execution_status != ExecutionStatus.SUCCEEDED
                ]
            )
        except asyncio.CancelledError:
            for event in cancel_events.values():
                event.set()
            now = utc_now()
            async with state_lock:
                current_look = current_look.model_copy(
                    update={
                        "items": [
                            item.model_copy(
                                update={
                                    "execution_status": ExecutionStatus.CANCELLED,
                                    "completed_at": now,
                                    "last_heartbeat_at": now,
                                    "error_code": "look_test_cancelled",
                                    "error_message": "用户停止了等待",
                                    "retryable": True,
                                }
                            )
                            if item.execution_status
                            in {ExecutionStatus.PENDING, ExecutionStatus.RUNNING}
                            else item
                            for item in current_look.items
                        ],
                        "execution_status": ExecutionStatus.CANCELLED,
                        "completed_at": now,
                        "last_heartbeat_at": now,
                        "error_message": "生成已停止；已完成图片会保留，可继续生成未完成项。",
                        "updated_at": now,
                    }
                )
                await self.repository.save_look_test(current_look)
                current_step = current_step.model_copy(
                    update={
                        "execution_status": ExecutionStatus.CANCELLED,
                        "error_code": "look_test_cancelled",
                        "error_message": "用户停止了等待",
                        "retryable": True,
                        "completed_at": now,
                        "last_heartbeat_at": now,
                        "total_ms": max(0, round((time.perf_counter() - started) * 1000)),
                    }
                )
                await self.repository.save_skill_step_run(current_step)
            return current_look
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        statuses = {item.execution_status for item in current_look.items}
        now = utc_now()
        if statuses == {ExecutionStatus.SUCCEEDED}:
            current_look = current_look.model_copy(
                update={
                    "execution_status": ExecutionStatus.SUCCEEDED,
                    "progress": 100,
                    "validation_status": ValidationStatus.PASSED,
                    "review_status": ReviewStatus.UNREVIEWED,
                    "provider": next(
                        (item.provider for item in current_look.items if item.provider),
                        current_look.provider,
                    ),
                    "model": next(
                        (item.model for item in current_look.items if item.model),
                        current_look.model,
                    ),
                    "completed_at": now,
                    "last_heartbeat_at": now,
                    "error_message": None,
                    "updated_at": now,
                }
            )
            await self.repository.save_look_test(current_look)
            await self._finish_step(
                current_step,
                [],
                started=started,
                provider_ms=metrics["provider_ms"],
                provider=current_look.provider,
                model=current_look.model,
                estimated_cost_micros=metrics["estimated"],
                actual_cost_micros=metrics["actual"],
            )
            return current_look

        cancelled_only = statuses.issubset({ExecutionStatus.SUCCEEDED, ExecutionStatus.CANCELLED})
        reconciliation_required = ExecutionStatus.BLOCKED in statuses
        terminal_status = (
            ExecutionStatus.BLOCKED
            if reconciliation_required
            else (ExecutionStatus.CANCELLED if cancelled_only else ExecutionStatus.FAILED)
        )
        current_look = current_look.model_copy(
            update={
                "execution_status": terminal_status,
                "validation_status": ValidationStatus.UNCHECKED,
                "completed_at": now,
                "last_heartbeat_at": now,
                "error_message": (
                    "存在已提交的 Provider 请求，确认结果前不会重复生成。"
                    if reconciliation_required
                    else (
                        "生成已停止；已完成图片会保留，可继续生成未完成项。"
                        if cancelled_only
                        else "部分图片生成失败；已完成图片已保留，可仅重试失败项。"
                    )
                ),
                "updated_at": now,
            }
        )
        await self.repository.save_look_test(current_look)
        if reconciliation_required:
            await self.repository.save_skill_step_run(
                current_step.model_copy(
                    update={
                        "execution_status": ExecutionStatus.BLOCKED,
                        "error_code": "provider_reconcile_required",
                        "error_message": current_look.error_message,
                        "retryable": False,
                        "completed_at": now,
                        "last_heartbeat_at": now,
                        "total_ms": max(0, round((time.perf_counter() - started) * 1000)),
                    }
                )
            )
        else:
            await self._fail_step(
                current_step,
                "look_test_cancelled" if cancelled_only else "look_test_partial_failure",
                current_look.error_message or "Look Test 未全部完成",
                retryable=True,
                started=started,
            )
        return current_look

    async def select_look_test(self, run_id: UUID, payload: LookTestSelection) -> LookTest:
        _, project = await self._require_run(run_id)
        look = max(
            await self.repository.list_look_tests(project.id),
            key=lambda item: item.updated_at,
            default=None,
        )
        if look is None or look.execution_status != ExecutionStatus.SUCCEEDED:
            raise _fail(409, "look_test_incomplete", "Look Test 尚未生成完成")
        if not set(payload.selected_candidate_ids).issubset(set(look.candidate_ids)):
            raise _fail(422, "look_test_candidate_invalid", "选择了不属于当前 Look Test 的候选")
        updated = look.model_copy(
            update={
                "selected_candidate_ids": payload.selected_candidate_ids,
                "review_status": ReviewStatus.APPROVED,
                "decision_note": payload.decision_note,
                "updated_at": utc_now(),
            }
        )
        saved = await self.repository.save_look_test(updated)
        await self._invalidate_gates_from(
            project.id,
            SkillGate.STYLE_APPROVED,
            "Look Test 采用结果已更新",
        )
        return saved

    async def compile_storyboard(self, run_id: UUID) -> SkillRunDetail:
        run, project = await self._require_run(run_id)
        await self._assert_budget(run)
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        bible = _latest(await self.repository.list_style_bible_revisions(project.id))
        snapshot = await self._require_snapshot(project.id)
        if brief is None or bible is None:
            raise _fail(409, "storyboard_inputs_missing", "请先完成简报和风格确认")
        gates = await self.repository.list_gate_decisions(run.id)
        if not self._gate_is_approved(gates, SkillGate.STYLE_APPROVED):
            raise _fail(409, "style_gate_required", "请先人工批准风格确认")
        input_hash = content_digest(
            {
                "brief": brief.input_hash,
                "style": bible.content_hash,
                "compiler": self.COMPILER_VERSION,
            }
        )
        step, reused = await self._begin_step(
            run,
            SkillWorkflowStage.STORYBOARD_DESIGN,
            "compile_storyboard",
            input_hash,
        )
        if reused:
            return await self.run_detail(run.id)
        started = time.perf_counter()
        patterns = snapshot.manifest.spec.narrative.outline_pattern
        beat_frames = _allocate_frames(
            brief.target_duration_frames,
            [item.target_duration_ratio for item in patterns],
        )
        outline_beats = [
            OutlineBeat(
                stable_beat_key=_stable_token("beat", project.id, brief.id, item.key),
                order=index,
                title=item.key.replace("_", " ").title(),
                purpose=item.purpose,
                target_duration_frames=beat_frames[index - 1],
                message=(
                    brief.required_messages[min(index - 1, len(brief.required_messages) - 1)]
                    if brief.required_messages
                    else brief.objective
                ),
            )
            for index, item in enumerate(patterns, start=1)
        ]
        outline_payload = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(await self.repository.list_outline_revisions(project.id)) + 1,
            "beats": outline_beats,
            "input_hash": input_hash,
            "created_at": utc_now(),
        }
        outline_payload["content_hash"] = content_digest(outline_payload)
        outline = OutlineRevision.model_validate(outline_payload)
        await self.repository.save_outline_revision(outline)
        target_count = min(
            snapshot.manifest.spec.narrative.shot_count.max,
            max(
                snapshot.manifest.spec.narrative.shot_count.min,
                len(outline_beats),
                round(brief.target_duration_seconds / 3),
            ),
        )
        shots_per_beat = [1] * len(outline_beats)
        for index in range(target_count - len(outline_beats)):
            shots_per_beat[index % len(shots_per_beat)] += 1
        usages = await self.repository.list_asset_usages(project.id)
        role_specs = {item.role: item for item in snapshot.manifest.spec.intake.asset_roles}
        image_usages = [
            item
            for item in usages
            if item.fidelity != Fidelity.EXACT and "image" in role_specs.get(item.role).media_types
        ]
        video_usages = [item for item in usages if "video" in role_specs.get(item.role).media_types]
        exact_usages = [item for item in usages if item.fidelity == Fidelity.EXACT]
        shots: list[ShotManifestShot] = []
        cursor = 0
        order = 1
        for beat, shot_count in zip(outline_beats, shots_per_beat, strict=True):
            durations = _allocate_frames(beat.target_duration_frames, [1.0] * shot_count)
            for local_index, duration in enumerate(durations, start=1):
                shot_key = _stable_token(
                    "shot",
                    project.id,
                    outline.id,
                    beat.stable_beat_key,
                    local_index,
                )
                static_description = (
                    f"{beat.purpose}；主体与场景呈现“{beat.message}”，"
                    f"遵循 {'、'.join(bible.positive_lock)}。"
                )
                assigned_exact = [
                    item
                    for item in exact_usages
                    if (
                        shot_key in item.required_in_shot_keys
                        if item.required_in_shot_keys
                        else order == target_count
                    )
                ]
                exact_overlays = [
                    {
                        "asset_usage_id": item.id,
                        "placement": ("bottom_right" if index % 2 == 0 else "bottom_left"),
                        "scale_mode": "contain",
                        "start_frame": cursor,
                        "end_frame": cursor + duration,
                        "tracking_mode": "static",
                        "occlusion_policy": "preserve",
                        "blend_mode": "normal",
                        "safe_area": "title_safe",
                        "required_review": True,
                    }
                    for index, item in enumerate(assigned_exact)
                ]
                shot_image_usage_ids = [
                    item.id
                    for item in image_usages
                    if not item.required_in_shot_keys or shot_key in item.required_in_shot_keys
                ]
                shot_video_usage_ids = [
                    item.id
                    for item in video_usages
                    if not item.required_in_shot_keys or shot_key in item.required_in_shot_keys
                ]
                exact_reservation = (
                    "\n【确定性叠加预留】为后期 exact 素材保留安全留白；"
                    "不要生成、临摹或重绘 Logo、包装文字、认证标识。"
                    if exact_overlays
                    else ""
                )
                image_prompt = (
                    f"【主体与场景】{static_description}\n"
                    f"【构图与光线】{bible.composition}；{bible.lighting}\n"
                    f"【色彩与质感】{bible.palette}；{bible.texture}"
                    f"{exact_reservation}"
                )
                video_prompt = (
                    f"以上一阶段采用图片为唯一首帧视觉依据。镜头 {order}：{beat.purpose}。"
                    f"动作在 {duration / brief.fps:.2f} 秒内完整发展；"
                    f"运镜遵循 {bible.camera}，节奏遵循 {bible.rhythm}。"
                )
                shot_input = content_digest(
                    {
                        "outline": outline.content_hash,
                        "style": bible.content_hash,
                        "shot_key": shot_key,
                        "image_prompt": image_prompt,
                        "video_prompt": video_prompt,
                        "image_asset_usage_ids": shot_image_usage_ids,
                        "video_reference_usage_ids": shot_video_usage_ids,
                        "exact_overlays": exact_overlays,
                    }
                )
                shots.append(
                    ShotManifestShot(
                        stable_shot_key=shot_key,
                        order=order,
                        narrative_role=beat.title,
                        start_frame=cursor,
                        duration_frames=duration,
                        handle_in_frames=min(6, cursor),
                        handle_out_frames=6,
                        description=static_description,
                        image_prompt=image_prompt,
                        image_negative_constraints=bible.negative_lock,
                        video_prompt=video_prompt,
                        video_negative_constraints=bible.negative_lock,
                        image_asset_usage_ids=shot_image_usage_ids,
                        video_reference_usage_ids=shot_video_usage_ids,
                        exact_overlays=exact_overlays,
                        continuity_group_ids=[beat.stable_beat_key],
                        dialogue_or_voiceover=beat.message,
                        caption_intent=beat.message,
                        input_hash=shot_input,
                    )
                )
                cursor += duration
                order += 1
        manifest_payload = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(await self.repository.list_shot_manifest_revisions(project.id))
            + 1,
            "outline_revision_id": outline.id,
            "style_bible_revision_id": bible.id,
            "fps": brief.fps,
            "shots": shots,
            "input_hash": content_digest(
                {"outline": outline.content_hash, "style": bible.content_hash}
            ),
            "created_at": utc_now(),
        }
        manifest_payload["content_hash"] = content_digest(manifest_payload)
        manifest = ShotManifestRevision.model_validate(manifest_payload)
        await self.repository.save_shot_manifest_revision(manifest)
        artifact = await self._save_structured_artifact(
            project.id,
            step.id,
            "shot_manifest",
            manifest.model_dump(mode="json"),
            step.input_hash,
            manifest.revision_number,
        )
        await self._save_dependencies(
            artifact,
            [
                ("style_bible", str(bible.id), bible.content_hash),
                ("outline", str(outline.id), outline.content_hash),
            ],
        )
        await self._finish_step(step, [artifact.id], started=started)
        await self.projects.bind_skill_run(project.id, stage=ProjectStage.STORYBOARD_DESIGN)
        return await self.run_detail(run.id)

    async def put_outline(self, project_id: UUID, payload: OutlineUpdate) -> OutlineRevision:
        project = await self._require_skill_project(project_id)
        current = await self.repository.list_outline_revisions(project.id)
        if sorted(item.order for item in payload.beats) != list(range(1, len(payload.beats) + 1)):
            raise _fail(422, "outline_order_invalid", "大纲顺序必须从 1 连续编号")
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        if brief is None:
            raise _fail(409, "brief_required", "请先完成创作简报")
        if (
            sum(item.target_duration_frames for item in payload.beats)
            != brief.target_duration_frames
        ):
            raise _fail(422, "outline_duration_invalid", "大纲总帧数必须等于创作简报目标帧数")
        input_hash = content_digest([item.model_dump(mode="json") for item in payload.beats])
        material = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(current) + 1,
            "beats": payload.beats,
            "input_hash": input_hash,
            "created_at": utc_now(),
        }
        material["content_hash"] = content_digest(material)
        item = OutlineRevision.model_validate(material)
        await self.repository.save_outline_revision(item)
        if current:
            await self.mark_dependency_stale(
                DependencyImpactRequest(
                    depends_on_type="outline",
                    depends_on_id=str(current[-1].id),
                    next_digest=item.content_hash,
                ),
                apply=True,
            )
            await self._invalidate_gates_from(
                project.id,
                SkillGate.STORYBOARD_APPROVED,
                "大纲已更新",
            )
        return item

    async def put_shot_manifest(
        self, project_id: UUID, payload: ShotManifestUpdate
    ) -> ShotManifestRevision:
        project = await self._require_skill_project(project_id)
        current = await self.repository.list_shot_manifest_revisions(project.id)
        outlines = await self.repository.list_outline_revisions(project.id)
        bibles = await self.repository.list_style_bible_revisions(project.id)
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        outline = _latest(outlines)
        bible = _latest(bibles)
        if outline is None or bible is None or brief is None:
            raise _fail(409, "storyboard_inputs_missing", "分镜编辑缺少当前大纲、风格或简报")
        if payload.outline_revision_id != outline.id or payload.style_bible_revision_id != bible.id:
            raise _fail(409, "storyboard_revision_stale", "分镜必须绑定当前大纲和风格版本")
        if payload.fps != brief.fps:
            raise _fail(422, "storyboard_fps_invalid", "分镜帧率必须与创作简报一致")
        previous_keys = {item.stable_shot_key for item in current[-1].shots} if current else set()
        incoming_keys = [item.stable_shot_key for item in payload.shots]
        if len(incoming_keys) != len(set(incoming_keys)):
            raise _fail(422, "shot_key_duplicate", "stable_shot_key 不能重复")
        ordered_shots = sorted(payload.shots, key=lambda item: item.order)
        if [item.order for item in ordered_shots] != list(range(1, len(ordered_shots) + 1)):
            raise _fail(422, "shot_order_invalid", "分镜顺序必须从 1 连续编号")
        cursor = 0
        normalized_shots: list[ShotManifestShot] = []
        for shot in ordered_shots:
            if shot.start_frame != cursor:
                raise _fail(422, "shot_frame_range_invalid", "分镜帧范围必须从 0 连续排列")
            shot_material = shot.model_dump(mode="python", exclude={"input_hash"})
            normalized_shots.append(
                ShotManifestShot(
                    **shot_material,
                    input_hash=content_digest(shot_material),
                )
            )
            cursor += shot.duration_frames
        if cursor != brief.target_duration_frames:
            raise _fail(422, "shot_duration_invalid", "分镜总帧数必须等于创作简报目标帧数")
        # Existing keys are retained exactly; only genuinely new shots may introduce a new key.
        if current and not previous_keys.intersection(incoming_keys):
            raise _fail(422, "shot_identity_lost", "编辑分镜时必须保留已有稳定镜头身份")
        material = {
            "id": uuid4(),
            "project_id": project.id,
            "revision_number": len(current) + 1,
            **payload.model_dump(mode="python", exclude={"shots"}),
            "shots": normalized_shots,
            "input_hash": content_digest(payload),
            "created_at": utc_now(),
        }
        material["content_hash"] = content_digest(material)
        item = ShotManifestRevision.model_validate(material)
        await self.repository.save_shot_manifest_revision(item)
        if current:
            old_by_key = {shot.stable_shot_key: shot for shot in current[-1].shots}
            for shot in item.shots:
                old = old_by_key.get(shot.stable_shot_key)
                if old and old.input_hash != shot.input_hash:
                    await self.mark_dependency_stale(
                        DependencyImpactRequest(
                            depends_on_type="shot",
                            depends_on_id=shot.stable_shot_key,
                            next_digest=shot.input_hash,
                        ),
                        apply=True,
                    )
            await self._invalidate_gates_from(
                project.id,
                SkillGate.STORYBOARD_APPROVED,
                "分镜提示词或时长已更新",
            )
        return item

    async def decide_gate(
        self,
        run_id: UUID,
        gate: SkillGate,
        payload: GateDecisionRequest,
    ) -> GateDecision:
        run, project = await self._require_run(run_id)
        account = await self.account_context.current_account()
        if payload.decision == GateDecisionValue.SKIP:
            snapshot = await self._require_snapshot(project.id)
            if (
                gate != SkillGate.STYLE_APPROVED
                or snapshot.manifest.spec.workflow.look_test.required
            ):
                raise _fail(409, "gate_skip_forbidden", "该人工门禁不能跳过")
        if payload.decision == GateDecisionValue.APPROVE:
            await self._validate_gate(run, project, gate, payload)
        decision = GateDecision(
            project_id=project.id,
            skill_run_id=run.id,
            gate=gate,
            decision=payload.decision,
            actor_type=GateActorType.USER,
            actor_id=account.id,
            note=payload.note,
            related_revision_ids=payload.related_revision_ids,
            created_at=self._next_gate_timestamp(await self.repository.list_gate_decisions(run.id)),
        )
        await self.repository.save_gate_decision(decision)
        if payload.decision == GateDecisionValue.REQUEST_REVISION:
            run = run.model_copy(
                update={
                    "current_stage": STAGE_BY_GATE[gate],
                    "execution_status": ExecutionStatus.RUNNING,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_skill_run(run)
            return decision
        next_index = GATE_ORDER.index(gate) + 1
        if gate == SkillGate.STORYBOARD_APPROVED:
            await self._create_production_from_storyboard(run, project)
        next_stage = (
            list(SkillWorkflowStage)[next_index]
            if next_index < len(SkillWorkflowStage)
            else SkillWorkflowStage.EXPORT
        )
        completed = gate == SkillGate.DELIVERY_APPROVED
        run = run.model_copy(
            update={
                "current_stage": next_stage,
                "execution_status": (
                    ExecutionStatus.SUCCEEDED if completed else ExecutionStatus.RUNNING
                ),
                "updated_at": utc_now(),
                "completed_at": utc_now() if completed else None,
            }
        )
        await self.repository.save_skill_run(run)
        await self.projects.bind_skill_run(
            project.id,
            stage=ProjectStage(next_stage.value),
            status=ProjectStatus.COMPLETED if completed else ProjectStatus.RUNNING,
        )
        if payload.decision == GateDecisionValue.APPROVE and not completed:
            await self._advance_full_auto(run, gate)
        return decision

    async def create_audio_asset(
        self,
        project_id: UUID,
        payload: AudioAssetCreate,
    ) -> AudioAsset:
        project = await self._require_skill_project(project_id)
        item = AudioAsset(
            project_id=project.id,
            **payload.model_dump(mode="python"),
        )
        return await self.repository.save_audio_asset(item)

    async def picture_lock_from_production(
        self,
        run_id: UUID,
        payload: ProductionPictureLockRequest,
    ) -> TimelineV3Revision:
        run, project = await self._require_run(run_id)
        if self.timeline_reader is None:
            raise _fail(503, "timeline_reader_unavailable", "剪辑时间线服务未启用")
        self._require_bound_production(project, payload.production_project_id)
        production_timeline = await self.timeline_reader.get_timeline(payload.production_project_id)
        if production_timeline.revision_id != payload.expected_timeline_revision_id:
            raise _fail(409, "timeline_revision_conflict", "剪辑时间线已变化，请刷新后重新锁定")
        clips, exact_overlays = await self._production_timeline_material(
            project,
            production_timeline,
        )
        timeline = await self.picture_lock(
            run.id,
            PictureLockRequest(
                production_project_id=payload.production_project_id,
                clips=clips,
                exact_overlays=exact_overlays,
            ),
        )
        updated_payload = timeline.model_dump(mode="python", exclude={"content_hash"})
        updated_payload["source_timeline_revision_id"] = production_timeline.revision_id
        updated_payload["content_hash"] = content_digest(updated_payload)
        updated = TimelineV3Revision.model_validate(updated_payload)
        await self.repository.save_timeline_v3_revision(updated)
        await self._invalidate_audio_after_picture_change(project.id, updated)
        return updated

    async def picture_lock(self, run_id: UUID, payload: PictureLockRequest) -> TimelineV3Revision:
        run, project = await self._require_run(run_id)
        self._require_bound_production(project, payload.production_project_id)
        gates = await self.repository.list_gate_decisions(run.id)
        if not self._gate_is_approved(gates, SkillGate.VIDEOS_APPROVED):
            raise _fail(409, "videos_gate_required", "请先批准全部分段视频")
        if any(clip.audio_source == "source" for clip in payload.clips):
            raise _fail(422, "skill_source_audio_unavailable", "Skill 项目不能选择原视频音轨")
        if any(
            clip.audio_source == "candidate" and not clip.candidate_audio_available
            for clip in payload.clips
        ):
            raise _fail(422, "candidate_audio_unavailable", "所选分镜视频没有可用候选音频")
        plans = await self.repository.list_shot_plans(payload.production_project_id)
        approved = {
            (item.stable_shot_key, item.approved_video_candidate_id)
            for item in plans
            if item.required
        }
        supplied = {(item.stable_shot_key, item.candidate_id) for item in payload.clips}
        if not approved or not approved.issubset(supplied):
            raise _fail(
                409, "picture_lock_candidates_invalid", "画面锁定必须包含全部已批准分镜视频"
            )
        contract = await self._run_contract(run)
        revisions = await self.repository.list_timeline_v3_revisions(project.id)
        revision_id = uuid4()
        material = {
            "id": revision_id,
            "project_id": project.id,
            "production_project_id": payload.production_project_id,
            "revision_number": len(revisions) + 1,
            "parent_revision_id": revisions[-1].id if revisions else None,
            "frame_rate": FrameRate(numerator=contract.video_fps),
            "video_clips": payload.clips,
            "picture_lock_revision_id": revision_id,
            "exact_overlays": payload.exact_overlays,
            "created_at": utc_now(),
        }
        material["content_hash"] = content_digest(material)
        timeline = TimelineV3Revision.model_validate(material)
        await self.repository.save_timeline_v3_revision(timeline)
        await self._invalidate_audio_after_picture_change(project.id, timeline)
        await self._invalidate_gates_from(
            project.id,
            SkillGate.PICTURE_LOCKED,
            "画面锁定版本已更新",
        )
        return timeline

    async def finalize_audio_caption_from_production(
        self,
        run_id: UUID,
        payload: ProductionAudioCaptionFinalize,
    ) -> TimelineV3Revision:
        run, project = await self._require_run(run_id)
        if self.timeline_reader is None:
            raise _fail(503, "timeline_reader_unavailable", "剪辑时间线服务未启用")
        self._require_bound_production(project, payload.production_project_id)
        gates = await self.repository.list_gate_decisions(run.id)
        if not self._gate_is_approved(gates, SkillGate.PICTURE_LOCKED):
            raise _fail(409, "picture_lock_gate_required", "请先人工确认画面锁定")
        production_timeline = await self.timeline_reader.get_timeline(payload.production_project_id)
        if production_timeline.revision_id != payload.expected_timeline_revision_id:
            raise _fail(409, "timeline_revision_conflict", "剪辑时间线已变化，请刷新后重试")
        source = _latest(await self.repository.list_timeline_v3_revisions(project.id))
        if source is None or source.picture_lock_revision_id is None:
            raise _fail(409, "picture_lock_required", "请先锁定画面时间线")
        current_clips, _ = await self._production_timeline_material(project, production_timeline)
        if self._visual_clip_digest(current_clips) != self._visual_clip_digest(source.video_clips):
            raise _fail(409, "picture_lock_stale", "画面剪辑已在 G5 后变化，请重新锁定画面")

        contract = await self._run_contract(run)
        audio_assets = await self.repository.list_audio_assets(project.id)
        narration: list[TimelineAudioItem] = []
        music: list[TimelineAudioItem] = []
        sfx: list[TimelineAudioItem] = []
        background = production_timeline.background_audio_track
        if background.enabled:
            if payload.background_audio_rights_status != RightsStatus.CONFIRMED:
                raise _fail(409, "audio_rights_not_confirmed", "请先确认附加音频的使用权利")
            try:
                audio_path, _ = await self.timeline_reader.resolve_background_audio(
                    payload.production_project_id
                )
            except Exception as exc:
                raise _fail(409, "background_audio_unavailable", "附加音频文件不可用") from exc
            sha256 = await asyncio.to_thread(_file_sha256, audio_path)
            asset = next(
                (
                    item
                    for item in audio_assets
                    if item.sha256 == sha256 and item.kind == payload.background_audio_kind
                ),
                None,
            )
            if asset is None:
                asset = await self.repository.save_audio_asset(
                    AudioAsset(
                        project_id=project.id,
                        kind=payload.background_audio_kind,
                        source="uploaded",
                        storage_uri=(
                            background.source_url
                            or background.source_relative_path
                            or str(audio_path)
                        ),
                        sha256=sha256,
                        duration_frames=max(
                            1,
                            seconds_to_frame(
                                background.source_duration_seconds
                                or production_timeline.duration_seconds,
                                contract.video_fps,
                            ),
                        ),
                        sample_rate=48_000,
                        channels=2,
                        rights_status=payload.background_audio_rights_status,
                    )
                )
            start_frame = seconds_to_frame(
                background.timeline_start_seconds,
                contract.video_fps,
            )
            end_seconds = (
                background.timeline_end_seconds
                if background.timeline_end_seconds is not None
                else production_timeline.duration_seconds
            )
            item = TimelineAudioItem(
                asset_id=asset.id,
                start_frame=start_frame,
                duration_frames=max(
                    1,
                    seconds_to_frame(end_seconds, contract.video_fps) - start_frame,
                ),
                source_in_frame=seconds_to_frame(
                    background.source_trim_in_seconds,
                    contract.video_fps,
                ),
                gain_db=_linear_gain_to_db(background.volume),
                loop=background.loop,
            )
            if payload.background_audio_kind == "music":
                music.append(item)
            elif payload.background_audio_kind == "narration":
                narration.append(item)
            else:
                sfx.append(item)
        elif contract.music_strategy != "none" or contract.narration_strategy != "none":
            raise _fail(409, "required_audio_missing", "运行契约要求的配乐或旁白尚未加入时间线")

        speech_revision_id = (
            production_timeline.revision_id
            if contract.subtitle_strategy == "final_speech"
            and any(item.enabled for item in production_timeline.subtitle_cues)
            else None
        )
        subtitles = [
            TimelineCaptionCue(
                start_frame=seconds_to_frame(item.start_seconds, contract.video_fps),
                end_frame=max(
                    seconds_to_frame(item.start_seconds, contract.video_fps) + 1,
                    seconds_to_frame(item.end_seconds, contract.video_fps),
                ),
                text=item.text,
                speech_revision_id=speech_revision_id,
            )
            for item in production_timeline.subtitle_cues
            if item.enabled
        ]
        timeline = await self.put_audio_caption(
            run.id,
            AudioCaptionUpdate(
                timeline_revision_id=source.id,
                narration=narration,
                music=music,
                sfx=sfx,
                subtitles=subtitles,
                subtitle_speech_revision_id=speech_revision_id,
                integrated_loudness_lufs=payload.integrated_loudness_lufs,
                true_peak_dbtp=payload.true_peak_dbtp,
            ),
        )
        updated_payload = timeline.model_dump(mode="python", exclude={"content_hash"})
        updated_payload.update(
            video_clips=current_clips,
            source_timeline_revision_id=production_timeline.revision_id,
        )
        updated_payload["content_hash"] = content_digest(updated_payload)
        updated = TimelineV3Revision.model_validate(updated_payload)
        await self.repository.save_timeline_v3_revision(updated)
        return updated

    async def put_audio_caption(
        self, run_id: UUID, payload: AudioCaptionUpdate
    ) -> TimelineV3Revision:
        _, project = await self._require_run(run_id)
        source = await self.repository.get_timeline_v3_revision(payload.timeline_revision_id)
        if (
            source is None
            or source.project_id != project.id
            or source.picture_lock_revision_id is None
        ):
            raise _fail(409, "picture_lock_required", "画面锁定后才能制作最终配乐和字幕")
        contract = _latest(await self.repository.list_run_contract_revisions(project.id))
        if (
            payload.subtitles
            and contract is not None
            and contract.subtitle_strategy == "final_speech"
            and payload.subtitle_speech_revision_id is None
        ):
            raise _fail(422, "speech_revision_required", "最终字幕必须绑定最终语音版本")
        audio_assets = {
            item.id: item for item in await self.repository.list_audio_assets(project.id)
        }
        typed_items = (
            [("narration", item) for item in payload.narration]
            + [("music", item) for item in payload.music]
            + [("sfx", item) for item in payload.sfx]
        )
        for expected_kind, item in typed_items:
            asset = audio_assets.get(item.asset_id)
            if asset is None or asset.kind != expected_kind:
                raise _fail(422, "audio_asset_invalid", "时间线引用了无效或类型不匹配的音频资产")
        revisions = await self.repository.list_timeline_v3_revisions(project.id)
        material = source.model_dump(mode="python", exclude={"id", "content_hash", "created_at"})
        material.update(
            id=uuid4(),
            revision_number=len(revisions) + 1,
            parent_revision_id=source.id,
            narration=payload.narration,
            music=payload.music,
            sfx=payload.sfx,
            subtitles=payload.subtitles,
            subtitle_speech_revision_id=payload.subtitle_speech_revision_id,
            created_at=utc_now(),
        )
        material["content_hash"] = content_digest(material)
        timeline = TimelineV3Revision.model_validate(material)
        await self.repository.save_timeline_v3_revision(timeline)
        has_audio = any(item.audio_source != "muted" for item in source.video_clips) or bool(
            payload.narration or payload.music or payload.sfx
        )
        mix_passed = not has_audio or (
            payload.integrated_loudness_lufs is not None
            and payload.true_peak_dbtp is not None
            and payload.true_peak_dbtp <= -1
        )
        mix_payload = {
            "id": uuid4(),
            "project_id": project.id,
            "timeline_revision_id": timeline.id,
            "revision_number": len(await self.repository.list_mix_revisions(project.id)) + 1,
            "integrated_loudness_lufs": payload.integrated_loudness_lufs,
            "true_peak_dbtp": payload.true_peak_dbtp,
            "validation_status": (
                ValidationStatus.PASSED if mix_passed else ValidationStatus.WARNING
            ),
            "validation_messages": ([] if mix_passed else ["尚未得到可靠的响度与峰值检查结果"]),
            "created_at": utc_now(),
        }
        mix_payload["content_hash"] = content_digest(mix_payload)
        mix = MixRevision.model_validate(mix_payload)
        await self.repository.save_mix_revision(mix)
        updated_payload = timeline.model_dump(mode="python", exclude={"content_hash"})
        updated_payload["mix_revision_id"] = mix.id
        updated_payload["content_hash"] = content_digest(updated_payload)
        timeline = TimelineV3Revision.model_validate(updated_payload)
        await self.repository.save_timeline_v3_revision(timeline)
        await self._invalidate_gates_from(
            project.id,
            SkillGate.AUDIO_CAPTION_APPROVED,
            "声音、混音或字幕版本已更新",
        )
        return timeline

    async def create_delivery_manifest(
        self, run_id: UUID, payload: DeliveryManifestCreate
    ) -> DeliveryManifest:
        run, project = await self._require_run(run_id)
        gates = await self.repository.list_gate_decisions(run.id)
        if not self._gate_is_approved(gates, SkillGate.AUDIO_CAPTION_APPROVED):
            raise _fail(409, "audio_caption_gate_required", "请先人工批准配乐和字幕")
        timeline = await self.repository.get_timeline_v3_revision(payload.timeline_revision_id)
        if (
            timeline is None
            or timeline.project_id != project.id
            or timeline.mix_revision_id is None
        ):
            raise _fail(409, "timeline_not_deliverable", "当前时间线尚未完成混音")
        usages = await self.repository.list_asset_usages(project.id)
        exact_usages = [item for item in usages if item.fidelity == Fidelity.EXACT]
        evidence_ids = {
            str(value)
            for item in payload.exact_overlay_evidence
            for value in (item.get("asset_usage_id"), item.get("asset_id"))
            if value
        }
        missing_exact = [
            item
            for item in exact_usages
            if str(item.id) not in evidence_ids and str(item.asset_id) not in evidence_ids
        ]
        if missing_exact:
            raise _fail(
                409,
                "exact_overlay_evidence_required",
                "exact 素材必须提供最终确定性叠加证据后才能交付",
            )
        if any(item.rights_status != RightsStatus.CONFIRMED for item in usages):
            raise _fail(409, "rights_not_confirmed", "交付前必须确认全部已使用素材的权利")
        referenced_audio_ids = {
            item.asset_id for item in (timeline.narration + timeline.music + timeline.sfx)
        }
        audio_assets = await self.repository.list_audio_assets(project.id)
        audio_by_id = {item.id: item for item in audio_assets}
        if any(
            audio_by_id.get(item_id) is None
            or audio_by_id[item_id].rights_status != RightsStatus.CONFIRMED
            for item_id in referenced_audio_ids
        ):
            raise _fail(409, "audio_rights_not_confirmed", "交付前必须确认全部音频资产的权利")
        material = {
            "id": uuid4(),
            "project_id": project.id,
            "skill_run_id": run.id,
            "production_project_id": payload.production_project_id,
            "timeline_revision_id": timeline.id,
            "files": payload.files,
            "rights_summary": {
                "status": "confirmed",
                "asset_usage_ids": [str(item.id) for item in usages],
                "audio_asset_ids": [str(item) for item in sorted(referenced_audio_ids, key=str)],
            },
            "quality_evidence": payload.quality_evidence,
            "exact_overlay_evidence": payload.exact_overlay_evidence,
            "created_at": utc_now(),
        }
        material["content_hash"] = content_digest(material)
        manifest = DeliveryManifest.model_validate(material)
        saved = await self.repository.save_delivery_manifest(manifest)
        await self._invalidate_gates_from(
            project.id,
            SkillGate.DELIVERY_APPROVED,
            "交付清单已更新",
        )
        return saved

    async def create_delivery_from_export(
        self,
        run_id: UUID,
        payload: DeliveryFromExportRequest,
    ) -> DeliveryManifest:
        run, project = await self._require_run(run_id)
        if self.export_reader is None:
            raise _fail(503, "export_reader_unavailable", "导出服务未启用")
        self._require_bound_production(project, payload.production_project_id)
        timeline = _latest(await self.repository.list_timeline_v3_revisions(project.id))
        if timeline is None or timeline.mix_revision_id is None:
            raise _fail(409, "timeline_not_deliverable", "请先完成 G6 声音与字幕版本")
        try:
            job = await self.export_reader.get_export(
                payload.production_project_id,
                payload.export_job_id,
            )
        except Exception as exc:
            raise _fail(404, "export_job_not_found", "导出任务不存在") from exc
        if str(job.status) not in {"succeeded", "TimelineRenderStatus.SUCCEEDED"}:
            raise _fail(409, "export_not_ready", "导出任务尚未成功完成")
        if (
            timeline.source_timeline_revision_id is None
            or job.timeline_revision_id != timeline.source_timeline_revision_id
        ):
            raise _fail(409, "export_timeline_mismatch", "导出产物不是当前 G6 已确认的时间线版本")
        summary = job.validation_summary
        if summary is None or not summary.valid or not job.output_url or not job.sha256:
            raise _fail(409, "export_validation_required", "导出产物尚未通过完整媒体校验")
        contract = await self._run_contract(run)
        if (summary.width, summary.height) != (contract.video_width, contract.video_height):
            raise _fail(
                409,
                "export_resolution_mismatch",
                "导出分辨率与项目创建时锁定的生成契约不一致",
            )
        timeline_has_audio = any(
            item.audio_source != "muted" for item in timeline.video_clips
        ) or bool(timeline.narration or timeline.music or timeline.sfx)
        if timeline_has_audio and not summary.has_audio:
            raise _fail(
                409,
                "export_audio_missing",
                "导出文件缺少 G6 已批准的声音轨道",
            )
        if timeline.subtitles and not summary.has_subtitles:
            raise _fail(
                409,
                "export_subtitles_missing",
                "导出文件缺少 G6 已批准的字幕",
            )
        return await self.create_delivery_manifest(
            run_id,
            DeliveryManifestCreate(
                production_project_id=payload.production_project_id,
                timeline_revision_id=timeline.id,
                files=[
                    {
                        "kind": "video",
                        "filename": job.output_filename or "final.mp4",
                        "storage_uri": job.output_url,
                        "sha256": job.sha256,
                        "byte_size": summary.size_bytes,
                        "media": summary.model_dump(mode="json"),
                    }
                ],
                quality_evidence=[
                    {
                        "export_job_id": str(job.id),
                        "validation": summary.model_dump(mode="json"),
                    }
                ],
                exact_overlay_evidence=payload.exact_overlay_evidence,
            ),
        )

    async def run_detail(self, run_id: UUID) -> SkillRunDetail:
        run = await self.repository.get_skill_run(run_id)
        if run is None:
            raise _fail(404, "skill_run_not_found", "Skill 运行不存在")
        return SkillRunDetail(
            run=run,
            steps=await self.repository.list_skill_step_runs(run.id),
            gates=await self.repository.list_gate_decisions(run.id),
        )

    async def run_metrics(self, run_id: UUID) -> SkillRunMetrics:
        detail = await self.run_detail(run_id)
        stage_metrics = {
            stage: self._stage_metrics(stage, detail.steps)
            for stage in SkillWorkflowStage
            if any(item.stage == stage for item in detail.steps)
        }
        project = await self.repository.get_project(detail.run.project_id)
        production_cost_micros = 0
        if (
            project is not None
            and project.kind == ProjectKind.SKILL
            and project.source_binding.active_skill_run_id == detail.run.id
            and project.source_binding.production_project_id is not None
        ):
            production_id = project.source_binding.production_project_id
            production = await self.repository.get_production_project(production_id)
            generation_runs = await self.repository.list_generation_runs(production_id)
            production_cost_micros = production.actual_cost_micros if production else 0
            for stage, kind in (
                (SkillWorkflowStage.SHOT_IMAGES, GenerationKind.IMAGE),
                (SkillWorkflowStage.SHOT_VIDEOS, GenerationKind.VIDEO),
            ):
                generated = self._generation_stage_metrics(
                    stage,
                    [item for item in generation_runs if item.kind == kind],
                )
                if generated.step_count:
                    stage_metrics[stage] = self._merge_stage_metrics(
                        stage_metrics.get(stage),
                        generated,
                    )
        stages = [stage_metrics[stage] for stage in SkillWorkflowStage if stage in stage_metrics]
        return SkillRunMetrics(
            run_id=detail.run.id,
            project_id=detail.run.project_id,
            stages=stages,
            queue_wait_ms=sum(item.queue_wait_ms for item in stages),
            provider_ms=sum(item.provider_ms for item in stages),
            postprocess_ms=sum(item.postprocess_ms for item in stages),
            total_ms=sum(item.total_ms for item in stages),
            estimated_cost_micros=detail.run.estimated_cost_micros,
            actual_cost_micros=detail.run.actual_cost_micros + production_cost_micros,
        )

    async def operations_summary(self) -> SkillOperationsSummary:
        groups: dict[str, dict[str, Any]] = {}
        for project in await self.repository.list_projects():
            if project.kind != ProjectKind.SKILL:
                continue
            snapshot = await self.repository.get_skill_version_snapshot(project.id)
            if snapshot is None:
                continue
            skill_id = snapshot.manifest.metadata.id
            group = groups.setdefault(
                skill_id,
                {
                    "skill_name": snapshot.manifest.metadata.name,
                    "runs": [],
                    "metrics": [],
                    "revision_requests": 0,
                },
            )
            for run in await self.repository.list_skill_runs(project.id):
                group["runs"].append(run)
                group["metrics"].append(await self.run_metrics(run.id))
                decisions = await self.repository.list_gate_decisions(run.id)
                group["revision_requests"] += sum(
                    item.decision == GateDecisionValue.REQUEST_REVISION for item in decisions
                )
        items: list[SkillOperationMetrics] = []
        for skill_id, material in sorted(groups.items()):
            runs: list[SkillRun] = material["runs"]
            metrics: list[SkillRunMetrics] = material["metrics"]
            items.append(
                SkillOperationMetrics(
                    skill_id=skill_id,
                    skill_name=material["skill_name"],
                    run_count=len(runs),
                    succeeded_count=sum(
                        item.execution_status == ExecutionStatus.SUCCEEDED for item in runs
                    ),
                    failed_count=sum(
                        item.execution_status == ExecutionStatus.FAILED for item in runs
                    ),
                    blocked_count=sum(
                        item.execution_status == ExecutionStatus.BLOCKED for item in runs
                    ),
                    revision_request_count=material["revision_requests"],
                    average_total_ms=(
                        round(sum(item.total_ms for item in metrics) / len(metrics)) if runs else 0
                    ),
                    average_actual_cost_micros=(
                        round(sum(item.actual_cost_micros for item in metrics) / len(metrics))
                        if runs
                        else 0
                    ),
                )
            )
        return SkillOperationsSummary(
            total_runs=sum(item.run_count for item in items),
            succeeded_runs=sum(item.succeeded_count for item in items),
            failed_runs=sum(item.failed_count for item in items),
            blocked_runs=sum(item.blocked_count for item in items),
            items=items,
        )

    @staticmethod
    def _stage_metrics(
        stage: SkillWorkflowStage,
        steps: list[SkillStepRun],
    ) -> SkillStageMetrics:
        selected = [item for item in steps if item.stage == stage]
        return SkillStageMetrics(
            stage=stage,
            step_count=len(selected),
            queue_wait_ms=sum(item.queue_wait_ms for item in selected),
            provider_ms=sum(item.provider_ms for item in selected),
            postprocess_ms=sum(item.postprocess_ms for item in selected),
            total_ms=sum(item.total_ms for item in selected),
            estimated_cost_micros=sum(item.estimated_cost_micros for item in selected),
            actual_cost_micros=sum(item.actual_cost_micros for item in selected),
            failed_step_count=sum(
                item.execution_status in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}
                for item in selected
            ),
            retry_count=sum(max(0, item.attempt - 1) for item in selected),
        )

    @staticmethod
    def _generation_stage_metrics(
        stage: SkillWorkflowStage,
        runs: list[GenerationRun],
    ) -> SkillStageMetrics:
        queue_wait_ms = 0
        provider_ms = 0
        total_ms = 0
        for run in runs:
            started_at = run.started_at or run.created_at
            finished_at = run.completed_at or run.updated_at
            queue = max(0, round((started_at - run.created_at).total_seconds() * 1000))
            total = max(queue, round((finished_at - run.created_at).total_seconds() * 1000))
            queue_wait_ms += queue
            provider_ms += min(max(0, run.latency_ms or 0), max(0, total - queue))
            total_ms += total
        postprocess_ms = max(0, total_ms - queue_wait_ms - provider_ms)
        return SkillStageMetrics(
            stage=stage,
            step_count=len(runs),
            queue_wait_ms=queue_wait_ms,
            provider_ms=provider_ms,
            postprocess_ms=postprocess_ms,
            total_ms=total_ms,
            estimated_cost_micros=sum(item.estimated_cost_micros for item in runs),
            actual_cost_micros=sum(item.actual_cost_micros for item in runs),
            failed_step_count=sum(
                item.status in {ProductionRunStatus.FAILED, ProductionRunStatus.BLOCKED}
                for item in runs
            ),
            retry_count=sum(item.retry_count for item in runs),
        )

    @staticmethod
    def _merge_stage_metrics(
        left: SkillStageMetrics | None,
        right: SkillStageMetrics,
    ) -> SkillStageMetrics:
        if left is None:
            return right
        return SkillStageMetrics(
            stage=right.stage,
            step_count=left.step_count + right.step_count,
            queue_wait_ms=left.queue_wait_ms + right.queue_wait_ms,
            provider_ms=left.provider_ms + right.provider_ms,
            postprocess_ms=left.postprocess_ms + right.postprocess_ms,
            total_ms=left.total_ms + right.total_ms,
            estimated_cost_micros=(left.estimated_cost_micros + right.estimated_cost_micros),
            actual_cost_micros=left.actual_cost_micros + right.actual_cost_micros,
            failed_step_count=left.failed_step_count + right.failed_step_count,
            retry_count=left.retry_count + right.retry_count,
        )

    async def cancel(self, run_id: UUID) -> SkillRunDetail:
        run, _ = await self._require_run(run_id)
        if run.execution_status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.CANCELLED}:
            return await self.run_detail(run.id)
        updated = run.model_copy(
            update={
                "cancel_requested_at": utc_now(),
                "execution_status": ExecutionStatus.CANCELLED,
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_skill_run(updated)
        return await self.run_detail(run.id)

    async def resume(self, run_id: UUID) -> SkillRunDetail:
        run, project = await self._require_run(run_id)
        check = await self.preflight(project.id)
        if not check.can_start:
            raise _fail(409, "preflight_blocked", "恢复前预检未通过")
        updated = run.model_copy(
            update={
                "execution_status": ExecutionStatus.RUNNING,
                "cancel_requested_at": None,
                "last_error": None,
                "resume_token": uuid4().hex,
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_skill_run(updated)
        return await self.run_detail(run.id)

    async def retry_step(self, run_id: UUID, step_id: UUID) -> SkillStepRun:
        run, _ = await self._require_run(run_id)
        step = await self.repository.get_skill_step_run(step_id)
        if step is None or step.skill_run_id != run.id:
            raise _fail(404, "skill_step_not_found", "运行步骤不存在")
        if not step.retryable or step.attempt >= 3:
            raise _fail(409, "retry_not_allowed", "该步骤不可重试或已达到三次上限")
        retry = SkillStepRun(
            skill_run_id=run.id,
            stage=step.stage,
            operation=step.operation,
            attempt=step.attempt + 1,
            input_hash=step.input_hash,
            execution_status=ExecutionStatus.PENDING,
            estimated_cost_micros=step.estimated_cost_micros,
        )
        return await self.repository.save_skill_step_run(retry)

    async def recover(self) -> None:
        """Reconcile interrupted work without replaying a paid provider request."""

        projects = await self.repository.list_projects()
        for project in projects:
            if project.kind != ProjectKind.SKILL:
                continue
            for run in await self.repository.list_skill_runs(project.id):
                if run.execution_status != ExecutionStatus.RUNNING:
                    continue
                steps = await self.repository.list_skill_step_runs(run.id)
                running = [
                    item for item in steps if item.execution_status == ExecutionStatus.RUNNING
                ]
                if not running:
                    continue
                run_requires_block = False
                for step in running:
                    interrupted_look: LookTest | None = None
                    interrupted_items: list[LookTestItem] = []
                    if step.operation == "generate_look_test":
                        look_tests = await self.repository.list_look_tests(project.id)
                        interrupted_look = max(
                            look_tests,
                            key=lambda item: item.updated_at,
                            default=None,
                        )
                        if interrupted_look is not None:
                            now = utc_now()
                            interrupted_items = [
                                item.model_copy(
                                    update={
                                        "execution_status": (
                                            ExecutionStatus.BLOCKED
                                            if item.request_id
                                            else ExecutionStatus.FAILED
                                        ),
                                        "completed_at": now,
                                        "last_heartbeat_at": now,
                                        "error_code": (
                                            "provider_reconcile_required"
                                            if item.request_id
                                            else "worker_interrupted"
                                        ),
                                        "error_message": (
                                            "Provider 请求已提交，需确认结果后再决定是否重试。"
                                            if item.request_id
                                            else "服务重启中断了该图片，可安全重试。"
                                        ),
                                        "retryable": not bool(item.request_id),
                                    }
                                )
                                if item.execution_status
                                in {
                                    ExecutionStatus.PENDING,
                                    ExecutionStatus.RUNNING,
                                }
                                else item
                                for item in interrupted_look.items
                            ]
                            blocked = any(
                                item.execution_status == ExecutionStatus.BLOCKED
                                for item in interrupted_items
                            )
                            succeeded = sum(
                                item.execution_status == ExecutionStatus.SUCCEEDED
                                for item in interrupted_items
                            )
                            interrupted_look = interrupted_look.model_copy(
                                update={
                                    "items": interrupted_items,
                                    "candidate_ids": [
                                        candidate_id
                                        for item in interrupted_items
                                        for candidate_id in item.candidate_ids
                                    ],
                                    "execution_status": (
                                        ExecutionStatus.BLOCKED
                                        if blocked
                                        else ExecutionStatus.FAILED
                                    ),
                                    "progress": round(
                                        succeeded * 100 / max(1, len(interrupted_items))
                                    ),
                                    "completed_at": now,
                                    "last_heartbeat_at": now,
                                    "error_message": (
                                        "部分图片需要确认 Provider 结果。"
                                        if blocked
                                        else "生成被服务重启中断；已完成图片已保留。"
                                    ),
                                    "updated_at": now,
                                }
                            )
                            await self.repository.save_look_test(interrupted_look)
                    has_external_request = bool(step.request_id) or any(
                        item.execution_status == ExecutionStatus.BLOCKED
                        for item in interrupted_items
                    )
                    run_requires_block = run_requires_block or (
                        step.operation != "generate_look_test" or has_external_request
                    )
                    updated_step = step.model_copy(
                        update={
                            "execution_status": (
                                ExecutionStatus.BLOCKED
                                if has_external_request
                                else ExecutionStatus.FAILED
                            ),
                            "error_code": (
                                "provider_reconcile_required"
                                if has_external_request
                                else "worker_interrupted"
                            ),
                            "error_message": (
                                "检测到已提交的 Provider 请求，恢复前必须先对账"
                                if has_external_request
                                else "服务重启中断了尚未提交的步骤，可安全重试"
                            ),
                            "retryable": not has_external_request,
                            "completed_at": utc_now(),
                        }
                    )
                    await self.repository.save_skill_step_run(updated_step)
                updated_run = run.model_copy(
                    update={
                        "execution_status": (
                            ExecutionStatus.BLOCKED
                            if run_requires_block
                            else ExecutionStatus.RUNNING
                        ),
                        "last_error": (
                            "服务重启后等待恢复确认"
                            if run_requires_block
                            else "Look Test 已中断；已完成图片保留，可继续生成未完成项"
                        ),
                        "worker_lease_id": None,
                        "worker_lease_expires_at": None,
                        "updated_at": utc_now(),
                    }
                )
                await self.repository.save_skill_run(updated_run)

    async def mark_dependency_stale(
        self,
        payload: DependencyImpactRequest,
        *,
        apply: bool = False,
    ) -> DependencyImpactResponse:
        dependencies = await self.repository.list_artifact_dependencies()
        artifacts_by_id: dict[UUID, Artifact] = {}
        all_projects = await self.repository.list_projects()
        for project in all_projects:
            for artifact in await self.repository.list_skill_artifacts(project.id):
                artifacts_by_id[artifact.id] = artifact
        affected: set[UUID] = {
            item.artifact_id
            for item in dependencies
            if item.depends_on_type == payload.depends_on_type
            and item.depends_on_id == payload.depends_on_id
            and item.depends_on_digest != payload.next_digest
        }
        changed = True
        while changed:
            changed = False
            for item in dependencies:
                if (
                    item.depends_on_type == "artifact"
                    and item.depends_on_id in {str(value) for value in affected}
                    and item.artifact_id not in affected
                ):
                    affected.add(item.artifact_id)
                    changed = True
        if apply:
            for artifact_id in affected:
                artifact = artifacts_by_id.get(artifact_id)
                if artifact is not None and not artifact.stale:
                    await self.repository.save_skill_artifact(
                        artifact.model_copy(update={"stale": True, "selected": False})
                    )
        ordered = sorted(affected, key=str)
        return DependencyImpactResponse(
            affected_artifact_ids=ordered,
            affected_count=len(ordered),
        )

    async def _validate_gate(
        self,
        run: SkillRun,
        project: Project,
        gate: SkillGate,
        payload: GateDecisionRequest,
    ) -> None:
        existing = await self.repository.list_gate_decisions(run.id)
        gate_index = GATE_ORDER.index(gate)
        for earlier in GATE_ORDER[:gate_index]:
            if not self._gate_is_approved(existing, earlier):
                raise _fail(409, "previous_gate_required", f"请先完成门禁 {earlier.value}")
        if gate == SkillGate.BRIEF_APPROVED:
            brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
            contract = await self._run_contract(run)
            if not (await self.preflight(project.id)).can_start:
                raise _fail(409, "preflight_blocked", "简报预检未通过")
            if (
                brief is None
                or brief.id not in payload.related_revision_ids
                or contract.id not in payload.related_revision_ids
            ):
                raise _fail(409, "gate_revision_stale", "G0 必须绑定当前简报与生成契约")
        elif gate == SkillGate.STYLE_APPROVED:
            bible = _latest(await self.repository.list_style_bible_revisions(project.id))
            look = max(
                await self.repository.list_look_tests(project.id),
                key=lambda item: item.updated_at,
                default=None,
            )
            if bible is None or look is None or look.review_status != ReviewStatus.APPROVED:
                raise _fail(
                    409,
                    "look_test_review_required",
                    "必须人工采用 Look Test 后才能批准风格",
                )
            if (
                bible.id not in payload.related_revision_ids
                or look.id not in payload.related_revision_ids
            ):
                raise _fail(409, "gate_revision_stale", "G1 必须绑定当前风格与 Look Test")
        elif gate == SkillGate.STORYBOARD_APPROVED:
            outline = _latest(await self.repository.list_outline_revisions(project.id))
            bible = _latest(await self.repository.list_style_bible_revisions(project.id))
            manifest = _latest(await self.repository.list_shot_manifest_revisions(project.id))
            if outline is None or bible is None or manifest is None:
                raise _fail(409, "shot_manifest_required", "请先生成并审核分镜方案")
            if (
                manifest.outline_revision_id != outline.id
                or manifest.style_bible_revision_id != bible.id
            ):
                raise _fail(409, "storyboard_revision_stale", "分镜方案未绑定当前大纲与风格")
            if (
                outline.id not in payload.related_revision_ids
                or manifest.id not in payload.related_revision_ids
            ):
                raise _fail(409, "gate_revision_stale", "G2 必须绑定当前大纲与分镜版本")
        elif gate in {SkillGate.IMAGES_APPROVED, SkillGate.VIDEOS_APPROVED}:
            production_id = project.source_binding.production_project_id
            if production_id is None:
                raise _fail(409, "production_required", "尚未创建后半程创作方案")
            plans = await self.repository.list_shot_plans(production_id)
            field = "image_status" if gate == SkillGate.IMAGES_APPROVED else "video_status"
            if not plans or any(
                getattr(item, field) != WorkflowItemStatus.APPROVED
                for item in plans
                if item.required
            ):
                raise _fail(409, "production_candidates_unapproved", "仍有必需分镜尚未采用")
        elif gate == SkillGate.PICTURE_LOCKED:
            revisions = await self.repository.list_timeline_v3_revisions(project.id)
            if not revisions or revisions[-1].picture_lock_revision_id is None:
                raise _fail(409, "picture_lock_required", "请先锁定画面时间线")
            if revisions[-1].id not in payload.related_revision_ids:
                raise _fail(409, "gate_revision_stale", "G5 必须绑定当前画面锁定版本")
        elif gate == SkillGate.AUDIO_CAPTION_APPROVED:
            revisions = await self.repository.list_timeline_v3_revisions(project.id)
            mixes = await self.repository.list_mix_revisions(project.id)
            if not revisions or not mixes or revisions[-1].mix_revision_id != mixes[-1].id:
                raise _fail(409, "mix_required", "请先完成配乐、字幕和混音预览")
            if mixes[-1].validation_status != ValidationStatus.PASSED:
                raise _fail(409, "mix_validation_required", "混音响度与峰值校验尚未通过")
            if (
                revisions[-1].id not in payload.related_revision_ids
                or mixes[-1].id not in payload.related_revision_ids
            ):
                raise _fail(409, "gate_revision_stale", "G6 必须绑定当前声音时间线与混音版本")
            contract = await self._run_contract(run)
            if contract.music_strategy != "none" and not revisions[-1].music:
                raise _fail(409, "music_required", "运行契约要求的全片配乐尚未加入")
            if contract.narration_strategy != "none" and not revisions[-1].narration:
                raise _fail(409, "narration_required", "运行契约要求的旁白尚未加入")
            if contract.subtitle_strategy != "none" and not revisions[-1].subtitles:
                raise _fail(409, "subtitles_required", "运行契约要求的最终字幕尚未加入")
            referenced_audio_ids = {
                item.asset_id
                for item in (revisions[-1].narration + revisions[-1].music + revisions[-1].sfx)
            }
            audio_assets = await self.repository.list_audio_assets(project.id)
            if any(
                item.id in referenced_audio_ids and item.rights_status != RightsStatus.CONFIRMED
                for item in audio_assets
            ):
                raise _fail(409, "audio_rights_not_confirmed", "音频资产权利尚未全部确认")
        elif gate == SkillGate.DELIVERY_APPROVED:
            manifests = await self.repository.list_delivery_manifests(project.id)
            if not manifests:
                raise _fail(409, "delivery_manifest_required", "请先生成交付清单")
            if manifests[-1].id not in payload.related_revision_ids:
                raise _fail(409, "gate_revision_stale", "G7 必须绑定当前交付清单")
        if not payload.related_revision_ids and gate in {
            SkillGate.BRIEF_APPROVED,
            SkillGate.STYLE_APPROVED,
            SkillGate.PICTURE_LOCKED,
            SkillGate.AUDIO_CAPTION_APPROVED,
            SkillGate.DELIVERY_APPROVED,
        }:
            raise _fail(422, "gate_revision_required", "批准时必须绑定当前版本")

    async def _create_production_from_storyboard(
        self,
        run: SkillRun,
        project: Project,
    ) -> None:
        if self.production_service is None:
            raise _fail(503, "production_service_unavailable", "后半程生产服务未启用")
        if project.source_binding.production_project_id is not None:
            return
        brief = _latest(await self.repository.list_creative_brief_revisions(project.id))
        bible = _latest(await self.repository.list_style_bible_revisions(project.id))
        manifest = _latest(await self.repository.list_shot_manifest_revisions(project.id))
        contract = await self.repository.get_run_contract_revision(run.run_contract_revision_id)
        if brief is None or bible is None or manifest is None or contract is None:
            raise _fail(409, "production_seed_inputs_missing", "ProductionSeed 输入不完整")
        snapshot = await self._require_snapshot(project.id)
        role_specs = {item.role: item for item in snapshot.manifest.spec.intake.asset_roles}
        usages = await self.repository.list_asset_usages(project.id)
        references = [
            ProductionSeedReference(
                id=item.id,
                asset_id=item.asset_id,
                role=item.role,
                name=item.role,
                media_kind=role_specs[item.role].media_types[0],
                sha256=item.snapshot_sha256,
                fidelity=item.fidelity.value,
                rights_status=item.rights_status.value,
            )
            for item in usages
        ]
        seed_shots = [
            ProductionSeedShot(
                **shot.model_dump(
                    mode="python",
                    exclude={"exact_overlays", "video_reference_usage_ids"},
                ),
                exact_overlays=shot.exact_overlays,
                video_reference_usage_ids=shot.video_reference_usage_ids,
            )
            for shot in manifest.shots
        ]
        seed = SkillProductionSeedBuilder().build(
            owner_project_id=project.id,
            skill_run_id=run.id,
            name=project.name,
            output_aspect_ratio=brief.output_aspect_ratio,
            output_width=contract.video_width,
            output_height=contract.video_height,
            fps=contract.video_fps,
            style_bible_revision_id=bible.id,
            style_bible_snapshot=bible.model_dump(mode="json"),
            shots=seed_shots,
            reference_assets=references,
            audio_intent=ProductionSeedAudioIntent(
                clip_audio_strategy=contract.audio_source_strategy,
                music_strategy=contract.music_strategy,
                narration_strategy=contract.narration_strategy,
            ),
            subtitle_intent=ProductionSeedSubtitleIntent(
                enabled=contract.subtitle_strategy != "none",
                language=brief.locale,
                source=(
                    "final_speech"
                    if contract.subtitle_strategy == "final_speech"
                    else contract.subtitle_strategy
                ),
            ),
        )
        await self.repository.save_production_seed(seed)
        detail = await self.production_service.create_project_from_seed(
            seed,
            budget_limit_micros=contract.budget_limit_micros,
        )
        await self.projects.bind_skill_run(
            project.id,
            production_project_id=detail.project.id,
            stage=ProjectStage.SHOT_IMAGES,
        )

    async def _advance_full_auto(self, run: SkillRun, gate: SkillGate) -> None:
        contract = await self._run_contract(run)
        if contract.automation_mode.value != "full_auto":
            return
        try:
            if gate == SkillGate.BRIEF_APPROVED:
                await self.compile_style(run.id)
                snapshot = await self._require_snapshot(run.project_id)
                if snapshot.manifest.spec.workflow.look_test.required:
                    await self.generate_look_test(run.id)
            elif gate == SkillGate.STYLE_APPROVED:
                await self.compile_storyboard(run.id)
            elif gate == SkillGate.STORYBOARD_APPROVED:
                await self._full_auto_generate_images(run, contract)
            elif gate == SkillGate.IMAGES_APPROVED:
                await self._full_auto_generate_videos(run, contract)
            elif gate == SkillGate.VIDEOS_APPROVED:
                await self._full_auto_prepare_editing(run)
        except Exception as exc:
            current = await self.repository.get_skill_run(run.id) or run
            await self.repository.save_skill_run(
                current.model_copy(
                    update={
                        "execution_status": ExecutionStatus.BLOCKED,
                        "last_error": str(exc),
                        "updated_at": utc_now(),
                    }
                )
            )

    async def _full_auto_generate_images(
        self,
        run: SkillRun,
        contract: RunContractRevision,
    ) -> None:
        if self.production_service is None:
            raise _fail(503, "production_service_unavailable", "后半程生产服务未启用")
        project = await self._require_skill_project(run.project_id)
        production_id = project.source_binding.production_project_id
        if production_id is None:
            raise _fail(409, "production_required", "尚未创建后半程创作方案")
        detail = await self.production_service.get_project(production_id)
        shots = await self.production_service.list_shots(production_id)
        for response in shots:
            plan = response.plan
            if not plan.required or plan.image_status == WorkflowItemStatus.APPROVED:
                continue
            input_mode = (
                ImageGenerationInputMode.KEYFRAME_EDIT
                if plan.source_keyframe_url or plan.source_keyframe_relative_path
                else ImageGenerationInputMode.TEXT_TO_IMAGE
            )
            await self.production_service.create_image_run(
                plan.id,
                ImageGenerationCreate(
                    expected_revision_id=detail.project.current_revision_id,
                    expected_shot_revision_id=plan.revision_id,
                    candidate_count=contract.candidate_count_by_stage.get("shot_image", 1),
                    input_mode=input_mode,
                    execution_mode="remote_api",
                    model_alias=contract.image_model_id,
                ),
            )

    async def _full_auto_generate_videos(
        self,
        run: SkillRun,
        contract: RunContractRevision,
    ) -> None:
        if self.production_service is None:
            raise _fail(503, "production_service_unavailable", "后半程生产服务未启用")
        project = await self._require_skill_project(run.project_id)
        production_id = project.source_binding.production_project_id
        if production_id is None:
            raise _fail(409, "production_required", "尚未创建后半程创作方案")
        detail = await self.production_service.get_project(production_id)
        if detail.project.active_step == ProductionStep.SHOT_IMAGES:
            detail = await self.production_service.advance(
                production_id,
                ProductionAdvanceRequest(
                    expected_revision_id=detail.project.current_revision_id,
                    target_step=ProductionStep.SHOT_VIDEOS,
                ),
            )
        shots = await self.production_service.list_shots(production_id)
        audio_strategy = (
            VideoGenerationAudioStrategy.GENERATE_NATIVE
            if contract.generate_video_audio
            else VideoGenerationAudioStrategy.MUTED
        )
        for response in shots:
            plan = response.plan
            if not plan.required or plan.video_status == WorkflowItemStatus.APPROVED:
                continue
            await self.production_service.create_video_run(
                plan.id,
                VideoGenerationCreate(
                    expected_revision_id=detail.project.current_revision_id,
                    expected_shot_revision_id=plan.revision_id,
                    candidate_count=contract.candidate_count_by_stage.get("shot_video", 1),
                    input_plan=VideoGenerationInputPlan(
                        sources=[VideoGenerationInputSource.APPROVED_IMAGES]
                    ),
                    execution_mode="remote_api",
                    model_alias=contract.video_model_id,
                    resolution=contract.video_resolution_label,
                    duration_seconds=plan.duration_seconds,
                    audio_strategy=audio_strategy,
                ),
            )

    async def _full_auto_prepare_editing(self, run: SkillRun) -> None:
        if self.production_service is None or self.timeline_reader is None:
            raise _fail(503, "timeline_reader_unavailable", "剪辑时间线服务未启用")
        project = await self._require_skill_project(run.project_id)
        production_id = project.source_binding.production_project_id
        if production_id is None:
            raise _fail(409, "production_required", "尚未创建后半程创作方案")
        detail = await self.production_service.get_project(production_id)
        if detail.project.active_step == ProductionStep.SHOT_VIDEOS:
            await self.production_service.advance(
                production_id,
                ProductionAdvanceRequest(
                    expected_revision_id=detail.project.current_revision_id,
                    target_step=ProductionStep.EDITING,
                ),
            )
        await self.timeline_reader.get_timeline(production_id)

    def _require_bound_production(
        self,
        project: Project,
        production_project_id: UUID,
    ) -> None:
        if project.source_binding.production_project_id != production_project_id:
            raise _fail(409, "production_binding_mismatch", "创作方案不属于当前 Skill 项目")

    async def _production_timeline_material(
        self,
        project: Project,
        timeline: ProductionTimeline,
    ) -> tuple[list[TimelineV3Clip], list[dict[str, Any]]]:
        self._require_bound_production(project, timeline.project_id)
        plans = await self.repository.list_shot_plans(timeline.project_id)
        plans_by_id = {item.id: item for item in plans}
        clips: list[TimelineV3Clip] = []
        for source in sorted(
            (item for item in timeline.clips if item.enabled),
            key=lambda item: item.order,
        ):
            plan = plans_by_id.get(source.shot_plan_id)
            if plan is None or not plan.stable_shot_key:
                raise _fail(409, "stable_shot_key_missing", "时间线片段缺少稳定分镜身份")
            audio_source = source.audio_mode.value
            if not timeline.audio_track.enabled or timeline.audio_track.strategy == "muted":
                audio_source = "muted"
            if audio_source == "source":
                raise _fail(422, "skill_source_audio_unavailable", "Skill 项目不能使用原视频音轨")
            if audio_source == "candidate" and not source.candidate_audio_available:
                raise _fail(422, "candidate_audio_unavailable", "所选分镜视频没有可用候选音频")
            transition_kind = source.transition_after.kind.value
            transition_frames = seconds_to_frame(
                source.transition_after.duration_seconds,
                timeline.fps,
            )
            clips.append(
                TimelineV3Clip(
                    stable_shot_key=plan.stable_shot_key,
                    candidate_id=source.candidate_id,
                    start_frame=seconds_to_frame(
                        source.timeline_start_seconds,
                        timeline.fps,
                    ),
                    duration_frames=max(
                        1,
                        seconds_to_frame(source.timeline_duration_seconds, timeline.fps),
                    ),
                    source_in_frame=seconds_to_frame(
                        source.trim_in_seconds,
                        timeline.fps,
                    ),
                    source_duration_frames=max(
                        1,
                        seconds_to_frame(
                            source.trim_out_seconds - source.trim_in_seconds,
                            timeline.fps,
                        ),
                    ),
                    handle_in_frames=plan.handle_in_frames,
                    handle_out_frames=plan.handle_out_frames,
                    audio_source=audio_source,
                    candidate_audio_available=source.candidate_audio_available,
                    transition_after=TimelineV3Transition(
                        kind=transition_kind,
                        duration_frames=transition_frames,
                    ),
                )
            )
        exact_overlays = [
            instruction for plan in plans for instruction in plan.exact_overlay_instructions
        ]
        return clips, exact_overlays

    @staticmethod
    def _visual_clip_digest(clips: list[TimelineV3Clip]) -> str:
        return content_digest(
            [
                item.model_dump(
                    mode="json",
                    exclude={"id", "audio_source", "candidate_audio_available"},
                )
                for item in clips
            ]
        )

    async def _begin_step(
        self,
        run: SkillRun,
        stage: SkillWorkflowStage,
        operation: str,
        input_hash: str,
    ) -> tuple[SkillStepRun, bool]:
        if run.cancel_requested_at is not None:
            raise _fail(409, "run_cancelled", "运行已取消")
        existing = await self.repository.list_skill_step_runs(run.id)
        cached = next(
            (
                item
                for item in reversed(existing)
                if item.operation == operation
                and item.input_hash == input_hash
                and item.execution_status == ExecutionStatus.SUCCEEDED
            ),
            None,
        )
        if cached is not None:
            return cached, True
        submitted = next(
            (
                item
                for item in reversed(existing)
                if item.operation == operation
                and item.input_hash == input_hash
                and item.request_id
                and item.execution_status != ExecutionStatus.SUCCEEDED
            ),
            None,
        )
        if submitted is not None:
            raise _fail(
                409,
                "provider_reconcile_required",
                "该输入已提交 Provider 请求，必须先对账，不能重复发起付费调用",
            )
        running = next(
            (
                item
                for item in reversed(existing)
                if item.operation == operation
                and item.input_hash == input_hash
                and item.execution_status == ExecutionStatus.RUNNING
            ),
            None,
        )
        if running is not None:
            raise _fail(409, "step_already_running", "相同输入的步骤正在执行")
        attempts = [item.attempt for item in existing if item.operation == operation]
        step = SkillStepRun(
            skill_run_id=run.id,
            stage=stage,
            operation=operation,
            attempt=max(attempts, default=0) + 1,
            input_hash=input_hash,
            execution_status=ExecutionStatus.RUNNING,
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
        )
        await self.repository.save_skill_step_run(step)
        return step, False

    async def _finish_step(
        self,
        step: SkillStepRun,
        artifacts: list[UUID],
        *,
        started: float,
        provider_ms: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        request_id: str | None = None,
        estimated_cost_micros: int | None = None,
        actual_cost_micros: int | None = None,
    ) -> SkillStepRun:
        total_ms = max(0, round((time.perf_counter() - started) * 1000))
        effective_provider_ms = step.provider_ms if provider_ms is None else provider_ms
        updated = step.model_copy(
            update={
                "execution_status": ExecutionStatus.SUCCEEDED,
                "validation_status": ValidationStatus.PASSED,
                "review_status": ReviewStatus.UNREVIEWED,
                "progress": 100,
                "provider_ms": effective_provider_ms,
                "postprocess_ms": max(0, total_ms - effective_provider_ms),
                "total_ms": total_ms,
                "provider": provider or step.provider,
                "model": model or step.model,
                "request_id": request_id or step.request_id,
                "estimated_cost_micros": (
                    step.estimated_cost_micros
                    if estimated_cost_micros is None
                    else estimated_cost_micros
                ),
                "actual_cost_micros": (
                    step.actual_cost_micros if actual_cost_micros is None else actual_cost_micros
                ),
                "output_artifact_ids": artifacts,
                "completed_at": utc_now(),
                "last_heartbeat_at": utc_now(),
            }
        )
        return await self.repository.save_skill_step_run(updated)

    async def _fail_step(
        self,
        step: SkillStepRun,
        code: str,
        message: str,
        *,
        retryable: bool,
        started: float,
    ) -> SkillStepRun:
        total_ms = max(0, round((time.perf_counter() - started) * 1000))
        return await self.repository.save_skill_step_run(
            step.model_copy(
                update={
                    "execution_status": ExecutionStatus.FAILED,
                    "error_code": code,
                    "error_message": message,
                    "retryable": retryable and step.attempt < 3,
                    "total_ms": total_ms,
                    "completed_at": utc_now(),
                    "last_heartbeat_at": utc_now(),
                }
            )
        )

    async def _save_structured_artifact(
        self,
        project_id: UUID,
        step_id: UUID,
        kind: str,
        value: dict[str, Any],
        input_hash: str,
        revision_number: int,
    ) -> Artifact:
        artifact = Artifact(
            project_id=project_id,
            kind=kind,
            revision_number=revision_number,
            source_step_run_id=step_id,
            content_hash=content_digest(value),
            input_hash=input_hash,
            producer_version=self.COMPILER_VERSION,
            generation_parameters={"structured": True},
            provenance={"compiler": self.COMPILER_VERSION},
        )
        return await self.repository.save_skill_artifact(artifact)

    async def _save_dependencies(
        self,
        artifact: Artifact,
        inputs: list[tuple[str, str, str]],
    ) -> None:
        for dependency_type, dependency_id, digest in inputs:
            await self.repository.save_artifact_dependency(
                ArtifactDependency(
                    artifact_id=artifact.id,
                    depends_on_type=dependency_type,
                    depends_on_id=dependency_id,
                    depends_on_digest=digest,
                )
            )

    async def _invalidate_audio_after_picture_change(
        self, project_id: UUID, timeline: TimelineV3Revision
    ) -> None:
        await self.mark_dependency_stale(
            DependencyImpactRequest(
                depends_on_type="picture_lock",
                depends_on_id=str(project_id),
                next_digest=timeline.content_hash,
            ),
            apply=True,
        )

    async def _invalidate_gates_from(
        self,
        project_id: UUID,
        first_gate: SkillGate,
        note: str,
    ) -> None:
        runs = await self.repository.list_skill_runs(project_id)
        run = max(runs, key=lambda item: item.updated_at, default=None)
        if run is None:
            return
        decisions = await self.repository.list_gate_decisions(run.id)
        invalidated = False
        first_index = GATE_ORDER.index(first_gate)
        for gate in GATE_ORDER[first_index:]:
            if not self._gate_is_approved(decisions, gate):
                continue
            decision = GateDecision(
                project_id=project_id,
                skill_run_id=run.id,
                gate=gate,
                decision=GateDecisionValue.REQUEST_REVISION,
                actor_type=GateActorType.SYSTEM,
                note=note,
                created_at=self._next_gate_timestamp(decisions),
            )
            await self.repository.save_gate_decision(decision)
            decisions.append(decision)
            invalidated = True
        if not invalidated:
            return
        updated_run = run.model_copy(
            update={
                "current_stage": STAGE_BY_GATE[first_gate],
                "execution_status": ExecutionStatus.RUNNING,
                "completed_at": None,
                "last_error": None,
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_skill_run(updated_run)
        await self.projects.bind_skill_run(
            project_id,
            stage=ProjectStage(STAGE_BY_GATE[first_gate].value),
            status=ProjectStatus.RUNNING,
        )

    async def _require_skill_project(self, project_id: UUID) -> Project:
        project = await self.repository.get_project(project_id)
        if project is None or project.trashed_at is not None:
            raise _fail(404, "project_not_found", "项目不存在")
        if project.kind != ProjectKind.SKILL:
            raise _fail(409, "skill_project_required", "该操作只适用于 Skill 项目")
        return project

    async def _require_snapshot(self, project_id: UUID) -> SkillVersionSnapshot:
        snapshot = await self.repository.get_skill_version_snapshot(project_id)
        if snapshot is None:
            raise _fail(409, "skill_snapshot_missing", "项目缺少不可变 Skill 快照")
        return snapshot

    async def _require_run(self, run_id: UUID) -> tuple[SkillRun, Project]:
        run = await self.repository.get_skill_run(run_id)
        if run is None:
            raise _fail(404, "skill_run_not_found", "Skill 运行不存在")
        project = await self._require_skill_project(run.project_id)
        return run, project

    async def _run_contract(self, run: SkillRun) -> RunContractRevision:
        contract = await self.repository.get_run_contract_revision(run.run_contract_revision_id)
        if contract is None:
            raise _fail(409, "run_contract_not_found", "运行契约不存在")
        return contract

    async def _assert_budget(self, run: SkillRun) -> None:
        contract = await self.repository.get_run_contract_revision(run.run_contract_revision_id)
        if contract is None:
            raise _fail(409, "run_contract_not_found", "运行契约不存在")
        projected = run.actual_cost_micros + max(
            0,
            run.estimated_cost_micros - run.actual_cost_micros,
        )
        if contract.budget_limit_micros is not None and projected > contract.budget_limit_micros:
            blocked = run.model_copy(
                update={
                    "execution_status": ExecutionStatus.BLOCKED,
                    "last_error": "预计成本超过预算上限",
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_skill_run(blocked)
            raise _fail(409, "budget_exceeded", "预计成本超过预算上限，已暂停运行")

    @staticmethod
    def _gate_is_approved(decisions: list[GateDecision], gate: SkillGate) -> bool:
        latest = max(
            (item for item in decisions if item.gate == gate),
            key=lambda item: item.created_at,
            default=None,
        )
        return latest is not None and latest.decision in {
            GateDecisionValue.APPROVE,
            GateDecisionValue.SKIP,
        }

    @staticmethod
    def _next_gate_timestamp(decisions: list[GateDecision]) -> datetime:
        now = utc_now()
        latest = max((item.created_at for item in decisions), default=None)
        if latest is None or now > latest:
            return now
        return latest + timedelta(microseconds=1)
