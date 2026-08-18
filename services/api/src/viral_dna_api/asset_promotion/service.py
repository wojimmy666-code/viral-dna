from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..asset_library import (
    Asset,
    AssetLibraryError,
    AssetLibraryService,
    AssetMediaKind,
    AssetOriginKind,
    AssetRightsBasis,
    AssetScope,
    AssetType,
    normalize_tags,
)
from ..generated_artifacts.domain import (
    AssetProvenance,
    GeneratedArtifact,
    GeneratedArtifactKind,
    StorageObjectReference,
    StorageReferenceOwner,
    StorageReferenceRole,
)
from ..generated_artifacts.repository import GeneratedArtifactRepository
from ..models import GenerationCandidate, GenerationKind, GenerationRun, ShotPlan
from ..storage_objects import StorageManager, StorageObjectType
from ..workspace import WorkspaceManager
from ..workspace_catalog import AccountContextService, StoragePolicy, StorageProviderType
from .contracts import (
    GeneratedArtifactBatchPromotionRequest,
    GeneratedArtifactBatchPromotionResponse,
    GeneratedArtifactPromotionRequest,
    GeneratedArtifactPromotionResponse,
    GeneratedArtifactPromotionStatus,
)
from .sync import LocalOnlySyncScheduler, ReplicaSyncScheduler


class ProductionArtifactRepository(GeneratedArtifactRepository, Protocol):
    async def get_generation_candidate(self, candidate_id: UUID) -> GenerationCandidate | None: ...
    async def get_generation_run(self, run_id: UUID) -> GenerationRun | None: ...
    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None: ...
    async def list_assets(self) -> list[Asset]: ...
    async def save_asset(self, asset: Asset) -> Asset: ...
    async def get_asset_folder(self, folder_id: UUID): ...


@dataclass(slots=True)
class ResolvedArtifactSource:
    kind: GeneratedArtifactKind
    source_entity_id: UUID
    project_id: UUID
    shot_plan_id: UUID
    revision_id: UUID | None
    generation_run_id: UUID | None
    content_relative_path: str
    content_sha256: str | None
    thumbnail_relative_path: str | None
    provider: str | None
    model: str | None
    prompt_snapshot: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    fps: float | None
    codec: str | None
    actual_cost_micros: int | None
    input_asset_ids: list[UUID]


class GeneratedAssetPromotionService:
    def __init__(
        self,
        *,
        repository: ProductionArtifactRepository,
        account_context: AccountContextService,
        workspace: WorkspaceManager,
        storage: StorageManager,
        assets: AssetLibraryService,
        sync_scheduler: ReplicaSyncScheduler | None = None,
    ) -> None:
        self.repository = repository
        self.account_context = account_context
        self.workspace = workspace
        self.storage = storage
        self.assets = assets
        self.sync_scheduler = sync_scheduler or LocalOnlySyncScheduler()
        self._lock = asyncio.Lock()

    async def status(
        self, kind: GeneratedArtifactKind, source_entity_id: UUID
    ) -> GeneratedArtifactPromotionStatus:
        context = await self.account_context.ensure_current()
        artifact = await self._find_artifact(context.account.id, kind, source_entity_id)
        if artifact is None:
            return GeneratedArtifactPromotionStatus(registered=False, promoted=False)
        asset = next(
            (
                item
                for item in await self.repository.list_assets()
                if item.account_id == context.account.id
                and item.origin_artifact_id == artifact.id
                and item.deleted_at is None
            ),
            None,
        )
        return GeneratedArtifactPromotionStatus(
            registered=True,
            artifact_id=artifact.id,
            promoted=asset is not None,
            asset_id=asset.id if asset else None,
        )

    async def promote(
        self, payload: GeneratedArtifactPromotionRequest
    ) -> GeneratedArtifactPromotionResponse:
        async with self._lock:
            context = await self.account_context.ensure_current()
            account_id = context.account.id
            workspace_id = context.active_workspace.id
            existing_artifact = await self._find_artifact(
                account_id, payload.kind, payload.source_entity_id
            )
            existing_asset = None
            if existing_artifact is not None:
                existing_asset = next(
                    (
                        item
                        for item in await self.repository.list_assets()
                        if item.account_id == account_id
                        and item.origin_artifact_id == existing_artifact.id
                        and item.deleted_at is None
                    ),
                    None,
                )
            if existing_asset is not None:
                provenance = await self.repository.get_asset_provenance(existing_asset.id)
                if provenance is None:
                    provenance = self._build_provenance(existing_asset, existing_artifact)
                    await self.repository.save_asset_provenance(provenance)
                return GeneratedArtifactPromotionResponse(
                    artifact_id=existing_artifact.id,
                    asset=await self.assets.get_asset(existing_asset.id),
                    provenance=provenance,
                    already_existed=True,
                )

            if payload.folder_id is not None:
                folder = await self.repository.get_asset_folder(payload.folder_id)
                if folder is None or folder.workspace_id != workspace_id or folder.deleted_at:
                    raise AssetLibraryError(
                        "资产目录不存在或不属于当前工作区",
                        status_code=404,
                        code="asset_folder_not_found",
                    )
            artifact = existing_artifact or await self._register_artifact(payload)
            asset = self._build_asset(payload, artifact)
            await self.repository.save_asset(asset)
            await self.repository.save_storage_object_reference(
                StorageObjectReference(
                    account_id=account_id,
                    workspace_id=workspace_id,
                    storage_object_id=artifact.content_object_id,
                    owner_type=StorageReferenceOwner.ASSET,
                    owner_id=asset.id,
                    role=StorageReferenceRole.CONTENT,
                )
            )
            if artifact.thumbnail_object_id is not None:
                await self.repository.save_storage_object_reference(
                    StorageObjectReference(
                        account_id=account_id,
                        workspace_id=workspace_id,
                        storage_object_id=artifact.thumbnail_object_id,
                        owner_type=StorageReferenceOwner.ASSET,
                        owner_id=asset.id,
                        role=StorageReferenceRole.THUMBNAIL,
                    )
                )
            provenance = self._build_provenance(asset, artifact)
            await self.repository.save_asset_provenance(provenance)
            await self.sync_scheduler.schedule_asset_sync(asset)
            return GeneratedArtifactPromotionResponse(
                artifact_id=artifact.id,
                asset=await self.assets.get_asset(asset.id),
                provenance=provenance,
            )

    async def promote_batch(
        self, payload: GeneratedArtifactBatchPromotionRequest
    ) -> GeneratedArtifactBatchPromotionResponse:
        return GeneratedArtifactBatchPromotionResponse(
            items=[await self.promote(item) for item in payload.items]
        )

    async def get_provenance(self, asset_id: UUID) -> AssetProvenance:
        context = await self.account_context.ensure_current()
        asset = next(
            (
                item
                for item in await self.repository.list_assets()
                if item.id == asset_id
                and item.account_id == context.account.id
                and item.deleted_at is None
            ),
            None,
        )
        if asset is None:
            raise AssetLibraryError(
                "资产不存在或不属于当前账户",
                status_code=404,
                code="asset_not_found",
            )
        provenance = await self.repository.get_asset_provenance(asset_id)
        if provenance is None or provenance.account_id != context.account.id:
            raise AssetLibraryError(
                "资产没有生成来源记录",
                status_code=404,
                code="asset_provenance_not_found",
            )
        return provenance

    async def _find_artifact(
        self, account_id: UUID, kind: GeneratedArtifactKind, source_entity_id: UUID
    ) -> GeneratedArtifact | None:
        return next(
            (
                item
                for item in await self.repository.list_generated_artifacts()
                if item.account_id == account_id
                and item.kind == kind
                and item.source_entity_id == source_entity_id
            ),
            None,
        )

    async def _register_artifact(
        self, payload: GeneratedArtifactPromotionRequest
    ) -> GeneratedArtifact:
        context = await self.account_context.ensure_current()
        local_location = next(
            (
                item
                for item in context.storage_locations
                if item.provider_type == StorageProviderType.LOCAL_FILESYSTEM
            ),
            None,
        )
        if local_location is None:
            raise AssetLibraryError(
                "当前工作区没有可用的本地存储位置",
                status_code=409,
                code="local_storage_unavailable",
            )
        self.storage.bind_local_location(local_location.id)
        source = await self._resolve_source(payload)
        content_path = self.workspace.resolve(source.content_relative_path)
        content_object = await self.storage.register_existing_local_object(
            account_id=context.account.id,
            workspace_id=context.active_workspace.id,
            storage_location_id=local_location.id,
            object_type=self._storage_object_type(source.kind),
            original_filename=content_path.name,
            mime_type=self._mime(content_path, source.kind),
            object_key=source.content_relative_path,
            expected_sha256=source.content_sha256,
        )
        thumbnail_object = None
        if source.thumbnail_relative_path:
            thumbnail_path = self.workspace.resolve(source.thumbnail_relative_path)
            thumbnail_object = await self.storage.register_existing_local_object(
                account_id=context.account.id,
                workspace_id=context.active_workspace.id,
                storage_location_id=local_location.id,
                object_type=StorageObjectType.THUMBNAIL,
                original_filename=thumbnail_path.name,
                mime_type=self._mime(thumbnail_path, GeneratedArtifactKind.IMAGE_CANDIDATE),
                object_key=source.thumbnail_relative_path,
            )
        artifact = GeneratedArtifact(
            account_id=context.account.id,
            workspace_id=context.active_workspace.id,
            kind=source.kind,
            source_entity_id=source.source_entity_id,
            project_id=source.project_id,
            shot_plan_id=source.shot_plan_id,
            generation_run_id=source.generation_run_id,
            revision_id=source.revision_id,
            content_object_id=content_object.id,
            thumbnail_object_id=thumbnail_object.id if thumbnail_object else None,
            provider=source.provider,
            model=source.model,
            prompt_snapshot=source.prompt_snapshot,
            input_asset_ids=source.input_asset_ids,
            width=source.width,
            height=source.height,
            duration_seconds=source.duration_seconds,
            fps=source.fps,
            codec=source.codec,
            actual_cost_micros=source.actual_cost_micros,
        )
        await self.repository.save_generated_artifact(artifact)
        for object_id, role in (
            (artifact.content_object_id, StorageReferenceRole.CONTENT),
            (artifact.thumbnail_object_id, StorageReferenceRole.THUMBNAIL),
        ):
            if object_id is not None:
                await self.repository.save_storage_object_reference(
                    StorageObjectReference(
                        account_id=artifact.account_id,
                        workspace_id=artifact.workspace_id,
                        storage_object_id=object_id,
                        owner_type=StorageReferenceOwner.GENERATED_ARTIFACT,
                        owner_id=artifact.id,
                        role=role,
                    )
                )
        return artifact

    async def _resolve_source(
        self, payload: GeneratedArtifactPromotionRequest
    ) -> ResolvedArtifactSource:
        if payload.kind in {
            GeneratedArtifactKind.IMAGE_CANDIDATE,
            GeneratedArtifactKind.VIDEO_CANDIDATE,
        }:
            candidate = await self.repository.get_generation_candidate(
                payload.source_entity_id
            )
            if candidate is None:
                raise AssetLibraryError(
                    "生成候选不存在",
                    status_code=404,
                    code="generated_candidate_not_found",
                )
            run = await self.repository.get_generation_run(candidate.generation_run_id)
            if run is None:
                raise AssetLibraryError(
                    "生成任务不存在",
                    status_code=404,
                    code="generation_run_not_found",
                )
            expected = (
                GenerationKind.IMAGE
                if payload.kind == GeneratedArtifactKind.IMAGE_CANDIDATE
                else GenerationKind.VIDEO
            )
            if candidate.kind != expected:
                raise AssetLibraryError(
                    "生成产物类型不匹配",
                    status_code=409,
                    code="artifact_kind_mismatch",
                )
            plan = await self.repository.get_shot_plan(run.shot_plan_id)
            if plan is None:
                raise AssetLibraryError("分镜不存在", status_code=404, code="shot_plan_not_found")
            prompt = (
                plan.image_prompt
                if candidate.kind == GenerationKind.IMAGE
                else plan.video_prompt
            )
            return ResolvedArtifactSource(
                kind=payload.kind,
                source_entity_id=candidate.id,
                project_id=run.project_id,
                shot_plan_id=run.shot_plan_id,
                revision_id=run.revision_id,
                generation_run_id=run.id,
                content_relative_path=candidate.relative_path,
                content_sha256=candidate.sha256,
                thumbnail_relative_path=candidate.thumbnail_relative_path,
                provider=run.provider,
                model=run.model,
                prompt_snapshot=prompt,
                width=candidate.width,
                height=candidate.height,
                duration_seconds=candidate.duration_seconds,
                fps=self._number(candidate.quality_report.get("fps")),
                codec=str(candidate.quality_report.get("codec") or "") or None,
                actual_cost_micros=run.actual_cost_micros,
                input_asset_ids=self._input_asset_ids(run.request_payload),
            )
        if payload.shot_plan_id is None:
            raise AssetLibraryError(
                "深度视频需要分镜 ID",
                status_code=422,
                code="shot_plan_id_required",
            )
        plan = await self.repository.get_shot_plan(payload.shot_plan_id)
        if plan is None:
            raise AssetLibraryError("分镜不存在", status_code=404, code="shot_plan_not_found")
        depth = next(
            (
                item
                for item in plan.depth_control_assets
                if item.id == payload.source_entity_id
            ),
            None,
        )
        if depth is None or not depth.relative_path:
            raise AssetLibraryError(
                "深度视频不存在或尚未完成",
                status_code=404,
                code="depth_control_not_ready",
            )
        return ResolvedArtifactSource(
            kind=payload.kind,
            source_entity_id=depth.id,
            project_id=plan.project_id,
            shot_plan_id=plan.id,
            revision_id=plan.revision_id,
            generation_run_id=None,
            content_relative_path=depth.relative_path,
            content_sha256=depth.sha256,
            thumbnail_relative_path=depth.thumbnail_relative_path,
            provider="local_depth",
            model=f"{depth.engine}:{depth.model_variant}",
            prompt_snapshot=None,
            width=depth.width,
            height=depth.height,
            duration_seconds=depth.duration_seconds,
            fps=depth.fps,
            codec="h264",
            actual_cost_micros=0,
            input_asset_ids=[],
        )

    def _build_asset(
        self, payload: GeneratedArtifactPromotionRequest, artifact: GeneratedArtifact
    ) -> Asset:
        asset_type = payload.asset_type or {
            GeneratedArtifactKind.IMAGE_CANDIDATE: AssetType.OTHER,
            GeneratedArtifactKind.VIDEO_CANDIDATE: AssetType.MOTION_REFERENCE,
            GeneratedArtifactKind.DEPTH_CONTROL: AssetType.SPATIAL_DEPTH,
        }[artifact.kind]
        media_kind = {
            GeneratedArtifactKind.IMAGE_CANDIDATE: AssetMediaKind.IMAGE,
            GeneratedArtifactKind.VIDEO_CANDIDATE: AssetMediaKind.VIDEO,
            GeneratedArtifactKind.DEPTH_CONTROL: AssetMediaKind.DEPTH_VIDEO,
        }[artifact.kind]
        name = (payload.name or f"{asset_type.value}-{str(artifact.source_entity_id)[:8]}").strip()
        return Asset(
            account_id=artifact.account_id,
            workspace_id=artifact.workspace_id,
            scope=AssetScope.WORKSPACE,
            folder_id=payload.folder_id,
            content_object_id=artifact.content_object_id,
            thumbnail_object_id=artifact.thumbnail_object_id or artifact.content_object_id,
            type=asset_type,
            content_type=asset_type,
            media_kind=media_kind,
            origin_kind={
                GeneratedArtifactKind.IMAGE_CANDIDATE: AssetOriginKind.GENERATED_IMAGE,
                GeneratedArtifactKind.VIDEO_CANDIDATE: AssetOriginKind.GENERATED_VIDEO,
                GeneratedArtifactKind.DEPTH_CONTROL: AssetOriginKind.GENERATED_DEPTH,
            }[artifact.kind],
            origin_artifact_id=artifact.id,
            rights_basis=AssetRightsBasis.SYSTEM_GENERATED,
            name=name[:120],
            description=payload.description,
            tags=normalize_tags(payload.tags),
            rights_confirmed=True,
            rights_note="ViralDNA 生成产物",
            storage_policy=StoragePolicy.LOCAL_ONLY,
            width=artifact.width or 1,
            height=artifact.height or 1,
            duration_seconds=artifact.duration_seconds,
            fps=artifact.fps,
            codec=artifact.codec,
        )

    @staticmethod
    def _build_provenance(asset: Asset, artifact: GeneratedArtifact) -> AssetProvenance:
        return AssetProvenance(
            account_id=artifact.account_id,
            workspace_id=artifact.workspace_id,
            asset_id=asset.id,
            artifact_id=artifact.id,
            artifact_kind=artifact.kind,
            source_entity_id=artifact.source_entity_id,
            project_id=artifact.project_id,
            shot_plan_id=artifact.shot_plan_id,
            generation_run_id=artifact.generation_run_id,
            revision_id=artifact.revision_id,
            provider=artifact.provider,
            model=artifact.model,
            prompt_snapshot=artifact.prompt_snapshot,
            input_asset_ids=artifact.input_asset_ids,
            actual_cost_micros=artifact.actual_cost_micros,
            source_snapshot=artifact.model_dump(mode="json"),
        )

    @staticmethod
    def _storage_object_type(kind: GeneratedArtifactKind) -> StorageObjectType:
        return {
            GeneratedArtifactKind.IMAGE_CANDIDATE: StorageObjectType.GENERATED_IMAGE,
            GeneratedArtifactKind.VIDEO_CANDIDATE: StorageObjectType.GENERATED_VIDEO,
            GeneratedArtifactKind.DEPTH_CONTROL: StorageObjectType.DEPTH_VIDEO,
        }[kind]

    @staticmethod
    def _mime(path: Path, kind: GeneratedArtifactKind) -> str:
        fallback = "image/png" if kind == GeneratedArtifactKind.IMAGE_CANDIDATE else "video/mp4"
        return mimetypes.guess_type(path.name)[0] or fallback

    @staticmethod
    def _number(value) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _input_asset_ids(payload: dict) -> list[UUID]:
        values = payload.get("input_asset_ids") or payload.get("reference_asset_ids") or []
        result: list[UUID] = []
        for value in values if isinstance(values, list) else []:
            try:
                result.append(UUID(str(value)))
            except ValueError:
                continue
        return list(dict.fromkeys(result))
