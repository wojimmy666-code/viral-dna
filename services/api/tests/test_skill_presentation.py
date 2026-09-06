from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import subprocess
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from viral_dna_api.platform_skills import PlatformSkillCatalogService, PlatformSkillError
from viral_dna_api.platform_skills.presentation import SkillPresentationService
from viral_dna_api.platform_skills.presentation_models import PresentationUpdate
from viral_dna_api.platform_skills.presentation_routes import create_skill_presentation_router


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 180), "#5533cc").save(buffer, "PNG")
    return buffer.getvalue()


async def setup(tmp_path):
    catalog = PlatformSkillCatalogService(tmp_path / "catalog.json")
    skill = (await catalog.list_catalog()).items[0]
    service = SkillPresentationService(catalog, tmp_path / "media")
    return catalog, skill, service


async def upload(service, skill, kind="image", data=None):
    asset = await service.upload(
        skill.id,
        kind,
        UploadFile(
            filename="../sample.png", file=io.BytesIO(data if data is not None else png_bytes())
        ),
    )
    await asyncio.gather(*list(service.tasks.values()))
    return await service.get(asset.id)


def payload(revision=0, image=None, video=None):
    item_id = uuid4()
    return PresentationUpdate(
        expected_revision=revision,
        primary_item_id=item_id if image or video else None,
        items=[
            {
                "id": item_id,
                "image_asset_id": image.id if image else None,
                "video_asset_id": video.id if video else None,
            }
        ]
        if image or video
        else [],
    )


def test_image_publish_clear_revision_and_manifest_isolation(tmp_path):
    async def scenario():
        catalog, skill, service = await setup(tmp_path)
        original_manifest = skill.current_version.model_dump(mode="json")
        asset = await upload(service, skill)
        assert asset.status == "ready"
        assert asset.original_filename == "sample.png"
        assert asset.source_sha256 == hashlib.sha256(png_bytes()).hexdigest()
        assert (service.folder(asset.id) / "source.bin").read_bytes() == png_bytes()
        path, mime = await service.content(asset.id, admin=True)
        assert mime == "image/webp"
        with Image.open(path) as image:
            assert image.size == (120, 180)
        with pytest.raises(PlatformSkillError) as unpublished:
            await service.content(asset.id)
        assert unpublished.value.status_code == 404
        saved = await service.save(skill.id, payload(image=asset))
        assert saved.revision == 1
        assert str(asset.id) in saved.cover_url
        updated = await catalog.get_catalog_item(skill.slug)
        assert updated.cover_url == saved.cover_url
        assert updated.fallback_cover_url == skill.cover_url
        assert updated.current_version.model_dump(mode="json") == original_manifest
        reloaded = PlatformSkillCatalogService(tmp_path / "catalog.json")
        assert (await reloaded.get_catalog_item(skill.slug)).presentation.revision == 1
        await service.content(asset.id)
        with pytest.raises(PlatformSkillError) as stale:
            await service.save(skill.id, payload(image=asset))
        assert stale.value.status_code == 409
        await service.save(skill.id, payload(1))
        assert (await catalog.get_catalog_item(skill.slug)).cover_url == skill.cover_url
        with pytest.raises(PlatformSkillError):
            await service.content(asset.id)
        assert path.is_file(), "Removing a binding must preserve the original asset"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case", ["wrong_skill", "wrong_kind", "not_ready", "missing_file", "unknown"]
)
def test_reject_invalid_bindings_without_replacing_cover(tmp_path, case):
    async def scenario():
        catalog, skill, service = await setup(tmp_path)
        asset = await upload(service, skill)
        await service.save(skill.id, payload(image=asset))
        candidate = await upload(service, skill)
        if case == "wrong_skill":
            candidate = await service.update(
                candidate, skill_id=(await catalog.list_catalog()).items[1].id
            )
        elif case == "wrong_kind":
            candidate = await service.update(candidate, kind="video")
        elif case == "not_ready":
            candidate = await service.update(candidate, status="processing")
        elif case == "missing_file":
            (service.folder(candidate.id) / "preview.webp").unlink()
        elif case == "unknown":
            candidate = candidate.model_copy(update={"id": uuid4()})
        with pytest.raises(PlatformSkillError):
            await service.save(skill.id, payload(1, image=candidate))
        assert str(asset.id) in (await catalog.get_catalog_item(skill.slug)).cover_url

    asyncio.run(scenario())


def test_contract_reserves_array_but_rejects_multiple_items():
    first = payload(image=type("Asset", (), {"id": uuid4()})())
    with pytest.raises(ValidationError):
        PresentationUpdate.model_validate({**first.model_dump(), "items": first.items * 2})
    with pytest.raises(ValidationError):
        PresentationUpdate(expected_revision=0, primary_item_id=uuid4())


def test_failed_upload_recovery_and_retry_preserve_old_presentation(tmp_path, monkeypatch):
    async def scenario():
        catalog, skill, service = await setup(tmp_path)
        good = await upload(service, skill)
        await service.save(skill.id, payload(image=good))
        invalid = await upload(service, skill, data=b"not an image")
        assert invalid.status == "failed" and invalid.error_message and invalid.retryable
        first, second = await asyncio.gather(service.retry(invalid.id), service.retry(invalid.id))
        assert first.id == second.id
        await asyncio.gather(*list(service.tasks.values()))
        assert (await service.get(invalid.id)).status == "failed"
        await service.update(invalid, status="processing")
        restarted = SkillPresentationService(catalog, tmp_path / "media")
        await restarted.recover()
        assert (await restarted.get(invalid.id)).status == "failed"
        assert not restarted.tasks
        assert str(good.id) in (await catalog.get_catalog_item(skill.slug)).cover_url
        for data, kind in [(b"", "image"), (b"#EXTM3U\nhttps://example.invalid/video", "video")]:
            with pytest.raises(PlatformSkillError):
                await upload(service, skill, kind=kind, data=data)
        monkeypatch.setattr("viral_dna_api.platform_skills.presentation.MAX_IMAGE_BYTES", 1)
        with pytest.raises(PlatformSkillError) as too_large:
            await upload(service, skill)
        assert too_large.value.status_code == 413

    asyncio.run(scenario())


def test_video_poster_precedence_and_browser_playable_derivative(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for real cover video acceptance")
    source = tmp_path / "portrait.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=120x180:r=10:d=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    async def scenario():
        catalog, skill, service = await setup(tmp_path)
        video = await upload(service, skill, kind="video", data=source.read_bytes())
        assert video.status == "ready", video.error_message
        assert video.poster_asset_id and video.duration_seconds > 0
        with Image.open((await service.content(video.poster_asset_id, admin=True))[0]) as poster:
            assert poster.height > poster.width
        info = json.loads(
            await asyncio.to_thread(
                subprocess.check_output,
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str((await service.content(video.id, admin=True))[0]),
                ]
            )
        )
        assert len(info["streams"]) == 1
        assert info["streams"][0]["codec_name"] == "h264"
        saved = await service.save(skill.id, payload(video=video))
        assert saved.cover_url == saved.poster_url
        assert str(video.id) in saved.video_url
        await service.content(video.poster_asset_id)
        image = await upload(service, skill)
        saved = await service.save(skill.id, payload(1, image=image, video=video))
        assert str(image.id) in saved.cover_url
        assert saved.poster_url != saved.cover_url
        assert (service.folder(video.id) / "source.bin").read_bytes() == source.read_bytes()

    asyncio.run(scenario())


def test_routes_admin_isolation_public_visibility_and_range(tmp_path):
    async def scenario():
        catalog, skill, service = await setup(tmp_path)

        async def require_admin(x_test_admin: str | None = Header(default=None)):
            if x_test_admin != "yes":
                raise HTTPException(403, "platform_admin_required")

        app = FastAPI()
        app.include_router(
            create_skill_presentation_router(service, require_admin), prefix="/api/v1"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            admin = {"X-Test-Admin": "yes"}
            base = f"/api/v1/admin/skills/{skill.id}"
            uploaded = await client.post(
                f"{base}/media",
                headers=admin,
                data={"kind": "image"},
                files={"file": ("test.png", png_bytes(), "image/png")},
            )
            assert uploaded.status_code == 202, uploaded.text
            await asyncio.gather(*list(service.tasks.values()))
            asset = await service.get(uploaded.json()["id"])
            paths = [
                ("GET", f"{base}/presentation"),
                ("PUT", f"{base}/presentation"),
                ("POST", f"{base}/media"),
                ("GET", f"/api/v1/admin/skill-media/{asset.id}"),
                ("POST", f"/api/v1/admin/skill-media/{asset.id}/retry"),
                ("GET", asset.content_url),
            ]
            for method, path in paths:
                assert (await client.request(method, path)).status_code == 403
            public = f"/api/v1/skill-media/{asset.id}/content"
            assert (await client.get(public)).status_code == 404
            response = await client.put(
                f"{base}/presentation",
                headers=admin,
                json=payload(image=asset).model_dump(mode="json"),
            )
            assert response.status_code == 200, response.text
            assert (await client.get(public)).status_code == 200
            ranged = await client.get(public, headers={"Range": "bytes=0-15"})
            assert ranged.status_code == 206 and len(ranged.content) == 16
            assert ranged.headers["cache-control"] == "private, no-cache"
            await service.save(skill.id, payload(1))
            assert (await client.get(public)).status_code == 404
            assert (await client.get(asset.content_url, headers=admin)).status_code == 200

    asyncio.run(scenario())
