from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationKind,
    ProductionProject,
    ShotPlan,
)
from viral_dna_api.video_references.domain import (
    PersonContentClass,
    ReferenceProxyKind,
    ReferenceProxyQualityStatus,
    ReferenceProxyStatus,
    VideoReferenceBinding,
    VideoReferenceMediaType,
    VideoReferenceRole,
    VideoReferenceSourceKind,
)
from viral_dna_api.video_references.proxies.contracts import (
    ProxyEngineCapability,
    ProxyGenerationOutput,
)
from viral_dna_api.video_references.proxies.dwpose.engine import DWPoseWholeBodyEngine
from viral_dna_api.video_references.proxies.service import ReferenceProxyService
from viral_dna_api.video_references.routes import create_video_reference_router
from viral_dna_api.workspace import WorkspaceManager


class FakeProxyEngine:
    capability = ProxyEngineCapability(
        engine="fake_privacy_proxy",
        version="test",
        kinds=(
            ReferenceProxyKind.SILHOUETTE_IMAGE,
            ReferenceProxyKind.SILHOUETTE_VIDEO,
        ),
        available=True,
        production_ready=True,
    )

    def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        kind: ReferenceProxyKind,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> ProxyGenerationOutput:
        assert source_path.is_file()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"privacy-proxy-without-source-pixels")
        thumbnail_path.write_bytes(b"proxy-thumbnail")
        return ProxyGenerationOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            media_type=(
                VideoReferenceMediaType.IMAGE
                if kind.value.endswith("_image")
                else VideoReferenceMediaType.VIDEO
            ),
            identity_removed=True,
            validation_message="fake engine verified identity removal",
            semantic_validation_status=ReferenceProxyQualityStatus.PASSED,
            quality_score=0.95,
        )


class FakeBrowserVideoEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def ensure_cached_preview(self, source_path: Path, preview_path: Path) -> Path:
        self.calls.append((source_path, preview_path))
        preview_path.write_bytes(b"browser-compatible-h264-preview")
        return preview_path


class FakeInstallableModelManager:
    def __init__(self, root: Path) -> None:
        self.detector_path = root / "yolox_l.onnx"
        self.pose_path = root / "dw-ll_ucoco_384.onnx"
        self.installed = False

    def validate(self, *, verify_hash: bool = True) -> tuple[bool, str]:
        del verify_hash
        return (
            (True, "DWPose WholeBody 模型已通过完整性校验")
            if self.installed
            else (False, "缺少 yolox_l.onnx；请安装 DWPose WholeBody 模型")
        )

    def install(self, progress=None) -> None:
        for downloaded, message in (
            (0, "准备下载"),
            (40, "正在下载 yolox_l.onnx"),
            (100, "模型下载与完整性校验完成"),
        ):
            if progress is not None:
                progress(downloaded, 100, message)
        self.installed = True


class FakeNotificationPublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, **payload):
        self.events.append(payload)
        return SimpleNamespace(**payload)


def _filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    return Path(f"{chr(92)}{chr(92)}?{chr(92)}{path}")


def _project_and_shot() -> tuple[ProductionProject, ShotPlan]:
    project = ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="动作代理测试",
        output_aspect_ratio="9:16",
        output_width=1080,
        output_height=1920,
    )
    shot = ShotPlan(
        project_id=project.id,
        revision_id=uuid4(),
        source_shot_id="shot-001",
        index=1,
        start_seconds=0,
        end_seconds=4,
        duration_seconds=4,
    )
    return project, shot


def test_image_and_source_video_proxies_are_distinct_persistable_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
        workspace = WorkspaceManager()
        service = ReferenceProxyService(workspace, engines=[FakeProxyEngine()])
        project, shot = _project_and_shot()
        source_image = workspace.root / "source-image.png"
        source_video = workspace.root / "source-video.mp4"
        source_image.write_bytes(b"source-image")
        source_video.write_bytes(b"source-video")
        candidate = GenerationCandidate(
            generation_run_id=uuid4(),
            ordinal=1,
            kind=GenerationKind.IMAGE,
            relative_path=workspace.relative(source_image),
            sha256="a" * 64,
            metadata_relative_path="source-image.json",
        )

        image_proxy = await service.generate(
            project=project,
            shot=shot,
            source_candidate=candidate,
            kind=ReferenceProxyKind.SILHOUETTE_IMAGE,
            visual_beat_id=shot.visual_beats[0].id,
        )
        video_proxy = await service.generate(
            project=project,
            shot=shot,
            source_path_override=source_video,
            source_video_id=project.video_id,
            start_seconds=shot.start_seconds,
            end_seconds=shot.end_seconds,
            kind=ReferenceProxyKind.SILHOUETTE_VIDEO,
            visual_beat_id=shot.visual_beats[0].id,
        )

        assert image_proxy.status == ReferenceProxyStatus.READY
        assert image_proxy.media_type == VideoReferenceMediaType.IMAGE
        assert image_proxy.source_image_candidate_id == candidate.id
        assert video_proxy.status == ReferenceProxyStatus.READY
        assert video_proxy.media_type == VideoReferenceMediaType.VIDEO
        assert video_proxy.source_video_id == project.video_id
        assert image_proxy.id != video_proxy.id
        assert _filesystem_path(workspace.resolve(image_proxy.relative_path)).is_file()
        assert _filesystem_path(workspace.resolve(video_proxy.relative_path)).is_file()

        image_path, image_media_type, image_name = await service.resolve_content(
            image_proxy
        )
        thumbnail_path, thumbnail_media_type, _ = await service.resolve_content(
            video_proxy,
            thumbnail=True,
        )
        video_path, video_media_type, video_name = await service.resolve_content(
            video_proxy
        )
        assert image_path == _filesystem_path(workspace.resolve(image_proxy.relative_path))
        assert image_media_type == "image/png"
        assert image_name.endswith(".png")
        assert thumbnail_path == _filesystem_path(
            workspace.resolve(video_proxy.thumbnail_relative_path)
        )
        assert thumbnail_media_type == "image/png"
        assert video_path == _filesystem_path(workspace.resolve(video_proxy.relative_path))
        assert video_media_type == "video/mp4"
        assert video_name.endswith(".mp4")

        verified_image_proxy = image_proxy.model_copy(
            update={
                "manifest_relative_path": "reference-proxies/pose-manifest.json",
                "quality_report_relative_path": "reference-proxies/quality-report.json",
                "model_sha256": "b" * 64,
            }
        )
        bindings = [
            VideoReferenceBinding(
                role=VideoReferenceRole.MOTION,
                source_kind=VideoReferenceSourceKind.GENERATED_PROXY,
                media_type=proxy.media_type,
                visual_beat_id=proxy.visual_beat_id,
                proxy_asset_id=proxy.id,
                person_class=PersonContentClass.NON_PHOTOREAL_PROXY,
                enabled=True,
            )
            for proxy in (verified_image_proxy, video_proxy)
        ]

        class FakeProductionService:
            async def get_shot(self, shot_plan_id):
                assert shot_plan_id == shot.id
                return SimpleNamespace(
                    plan=SimpleNamespace(
                        reference_proxy_assets=[verified_image_proxy, video_proxy],
                        video_reference_bindings=bindings,
                        managed_asset_bindings=[SimpleNamespace(id=uuid4())],
                        visual_beats=[],
                    )
                )

        app = FastAPI()
        app.include_router(
            create_video_reference_router(FakeProductionService(), service),
            prefix="/api/v1",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            image_response = await client.get(
                f"/api/v1/video-references/shots/{shot.id}/proxies/"
                f"{image_proxy.id}/content"
            )
            assert image_response.status_code == 200
            assert image_response.content == b"privacy-proxy-without-source-pixels"
            assert image_response.headers["content-type"] == "image/png"
            assert image_response.headers["content-disposition"].startswith("inline;")

            thumbnail_response = await client.get(
                f"/api/v1/video-references/shots/{shot.id}/proxies/"
                f"{video_proxy.id}/content?thumbnail=true"
            )
            assert thumbnail_response.status_code == 200
            assert thumbnail_response.content == b"proxy-thumbnail"
            assert thumbnail_response.headers["content-type"] == "image/png"

            download_response = await client.get(
                f"/api/v1/video-references/shots/{shot.id}/proxies/"
                f"{video_proxy.id}/content?download=true"
            )
            assert download_response.status_code == 200
            assert download_response.headers["content-disposition"].startswith(
                "attachment;"
            )

            range_response = await client.get(
                f"/api/v1/video-references/shots/{shot.id}/proxies/"
                f"{video_proxy.id}/content",
                headers={"Range": "bytes=0-4"},
            )
            assert range_response.status_code == 206
            assert range_response.content == b"priva"
            assert range_response.headers["content-range"].startswith("bytes 0-4/")

            strategy_response = await client.get(
                f"/api/v1/video-references/shots/{shot.id}/strategy",
                params={"model_alias": "seedance_2_0"},
            )
            assert strategy_response.status_code == 200
            assert strategy_response.json()["selected_proxy_count"] == 1

    import asyncio

    asyncio.run(scenario())


def test_legacy_opencv_video_proxy_is_served_through_cached_h264_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
        workspace = WorkspaceManager()
        browser_encoder = FakeBrowserVideoEncoder()
        service = ReferenceProxyService(
            workspace,
            engines=[FakeProxyEngine()],
            browser_video_encoder=browser_encoder,
        )
        project, shot = _project_and_shot()
        source_video = workspace.root / "source-video.mp4"
        source_video.write_bytes(b"legacy-mp4v-video")
        proxy = await service.generate(
            project=project,
            shot=shot,
            source_path_override=source_video,
            source_video_id=project.video_id,
            start_seconds=shot.start_seconds,
            end_seconds=shot.end_seconds,
            kind=ReferenceProxyKind.SILHOUETTE_VIDEO,
            visual_beat_id=shot.visual_beats[0].id,
        )
        legacy_proxy = proxy.model_copy(
            update={"engine": "opencv_silhouette", "engine_version": "1.0.0"}
        )

        preview_path, media_type, _ = await service.resolve_content(legacy_proxy)

        assert preview_path.name == "browser-preview.mp4"
        assert preview_path.read_bytes() == b"browser-compatible-h264-preview"
        assert media_type == "video/mp4"
        assert len(browser_encoder.calls) == 1

    import asyncio

    asyncio.run(scenario())


def test_dwpose_installation_runs_in_background_with_progress_and_notifications(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
        manager = FakeInstallableModelManager(tmp_path / "models")
        engine = DWPoseWholeBodyEngine(model_manager=manager)
        publisher = FakeNotificationPublisher()
        service = ReferenceProxyService(
            WorkspaceManager(),
            engines=[engine],
            notification_publisher=publisher,
        )
        installation = await service.start_engine_installation(
            "dwpose_wholebody_mannequin"
        )

        for _ in range(100):
            installation = service.engine_installation(installation.id)
            if installation.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)

        assert installation.status == "succeeded"
        assert installation.progress_percent == 100
        assert installation.downloaded_bytes == installation.total_bytes == 100
        assert installation.capability is not None
        assert installation.capability.available is True
        assert [item["status"] for item in publisher.events] == [
            "in_progress",
            "succeeded",
        ]

    import asyncio

    asyncio.run(scenario())
