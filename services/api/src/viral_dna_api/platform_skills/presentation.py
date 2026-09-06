from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from ..media import (
    JPEG_FULL_RANGE_FILTER,
    MediaProcessingError,
    MediaProcessor,
    _run_command,
    _run_image_command,
)
from .contracts import utc_now
from .presentation_models import PresentationItem, SkillMediaAsset, SkillPresentation
from .service import PlatformSkillError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_VIDEO_SECONDS = 120
MAX_IMAGE_PIXELS = 40_000_000


def _fail(code, message, status=422):
    return PlatformSkillError(status, code, message)


class SkillPresentationService:
    """Platform-owned display media, outside immutable Skill manifests."""

    def __init__(self, catalog, root: Path, processor_factory=MediaProcessor):
        self.catalog = catalog
        self.root = root.resolve()
        self.processor_factory = processor_factory
        self.tasks = {}
        self.limit = asyncio.Semaphore(2)
        self.lock = asyncio.Lock()

    def folder(self, asset_id: UUID) -> Path:
        path = (self.root / str(UUID(str(asset_id)))).resolve()
        if not path.is_relative_to(self.root):
            raise _fail("media_path_invalid", "素材存储位置无效")
        return path

    def _write(self, asset):
        folder = self.folder(asset.id)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f".{uuid4()}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(asset.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, folder / "asset.json")
        finally:
            temporary.unlink(missing_ok=True)

    async def get(self, asset_id):
        path = self.folder(asset_id) / "asset.json"
        try:
            return SkillMediaAsset.model_validate_json(
                await asyncio.to_thread(path.read_text, "utf-8")
            )
        except FileNotFoundError as exc:
            raise _fail("skill_media_not_found", "封面素材不存在", 404) from exc

    async def update(self, asset, **changes):
        result = asset.model_copy(update={**changes, "updated_at": utc_now()})
        await asyncio.to_thread(self._write, result)
        return result

    async def upload(self, skill_id, kind, upload):
        await self.catalog.get_platform_skill(skill_id)
        if kind not in {"image", "video"}:
            raise _fail("media_kind_invalid", "请选择封面图片或预览视频")
        now = utc_now()
        asset = SkillMediaAsset(
            skill_id=skill_id,
            kind=kind,
            original_filename=(upload.filename or "素材")
            .replace("\\", "/")
            .rsplit("/", 1)[-1][:180],
            created_at=now,
            updated_at=now,
        )
        folder = self.folder(asset.id)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        source = folder / "source.bin"
        limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
        digest, size, header = hashlib.sha256(), 0, b""
        try:
            with source.open("xb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise _fail(
                            "media_upload_too_large",
                            f"文件不能超过 {limit // (1024 * 1024)}MB",
                            413,
                        )
                    if not header:
                        header = chunk[:32]
                    digest.update(chunk)
                    await asyncio.to_thread(handle.write, chunk)
            if not size:
                raise _fail("media_empty", "上传文件为空")
            if kind == "video" and not (
                header[4:8] == b"ftyp" or header.startswith(b"\x1aE\xdf\xa3")
            ):
                raise _fail("media_format_invalid", "请上传 MP4、MOV 或 WebM 视频文件")
            asset = await self.update(asset, source_size=size, source_sha256=digest.hexdigest())
        except BaseException:
            # Only this newly-created incomplete upload, never an existing asset.
            await asyncio.to_thread(source.unlink, missing_ok=True)
            raise
        finally:
            await upload.close()
        self.schedule(asset.id)
        return asset

    def schedule(self, asset_id):
        if asset_id in self.tasks and not self.tasks[asset_id].done():
            return
        task = asyncio.create_task(self.process(asset_id), name=f"skill-cover-{asset_id}")
        self.tasks[asset_id] = task

        def completed(result):
            if self.tasks.get(asset_id) is result:
                self.tasks.pop(asset_id, None)
            if not result.cancelled():
                result.exception()

        task.add_done_callback(completed)

    @staticmethod
    def image_preview(source, target):
        try:
            with Image.open(source) as image:
                if (
                    image.format not in {"JPEG", "PNG", "WEBP"}
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise _fail("image_format_invalid", "请上传 JPG、PNG 或 WebP 静态图片")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise _fail("image_too_large", "图片像素过大，请缩小后再上传")
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1920, 1920))
                image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                    target, "WEBP", quality=86
                )
                return image.width, image.height
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise _fail("image_invalid", "无法读取图片，请检查文件是否完整") from exc

    async def process_video(self, asset):
        processor = self.processor_factory()
        folder, source = self.folder(asset.id), self.folder(asset.id) / "source.bin"
        stdout, _ = await _run_command(
            [
                processor.ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(source),
            ],
            timeout_seconds=30,
        )
        metadata = json.loads(stdout)
        stream = next(
            (item for item in metadata.get("streams", []) if item.get("codec_type") == "video"),
            None,
        )
        duration = float(
            metadata.get("format", {}).get("duration") or (stream or {}).get("duration") or 0
        )
        width, height = (
            int((stream or {}).get("width") or 0),
            int((stream or {}).get("height") or 0),
        )
        if (
            not stream
            or not math.isfinite(duration)
            or not 0 < duration <= MAX_VIDEO_SECONDS
            or not 0 < width * height <= MAX_IMAGE_PIXELS
        ):
            raise _fail("video_invalid", f"视频需包含有效画面，且不超过 {MAX_VIDEO_SECONDS} 秒")
        asset = await self.update(
            asset, phase="正在提取第一帧", progress=30, duration_seconds=duration
        )
        await _run_image_command(
            [
                processor.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                f"scale=1280:720:force_original_aspect_ratio=decrease,{JPEG_FULL_RANGE_FILTER}",
                "-threads",
                "1",
                str(folder / "first-frame.jpg"),
            ],
            folder / "first-frame.jpg",
            timeout_seconds=60,
            context="提取 Skill 视频首帧",
        )
        poster = SkillMediaAsset(
            skill_id=asset.skill_id,
            kind="image",
            original_filename="视频首帧",
            parent_asset_id=asset.id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        poster_folder = self.folder(poster.id)
        await asyncio.to_thread(poster_folder.mkdir, parents=True, exist_ok=True)
        width, height = await asyncio.to_thread(
            self.image_preview, folder / "first-frame.jpg", poster_folder / "preview.webp"
        )
        await self.update(
            poster, status="ready", phase="处理完成", progress=100, width=width, height=height
        )
        asset = await self.update(
            asset,
            phase="正在准备预览视频",
            progress=60,
            poster_asset_id=poster.id,
            width=width,
            height=height,
        )
        await _run_command(
            [
                processor.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "26",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-threads",
                "2",
                "-movflags",
                "+faststart",
                str(folder / "preview.mp4"),
            ],
            timeout_seconds=300,
        )
        if not (folder / "preview.mp4").is_file() or (folder / "preview.mp4").stat().st_size == 0:
            raise _fail("video_preview_missing", "未生成有效的预览视频")
        return asset

    async def process(self, asset_id):
        asset = await self.get(asset_id)
        try:
            async with self.limit:
                asset = await self.update(
                    asset,
                    status="processing",
                    phase="正在检查文件",
                    progress=10,
                    error_message=None,
                    retryable=False,
                )
                if asset.kind == "image":
                    folder = self.folder(asset.id)
                    width, height = await asyncio.to_thread(
                        self.image_preview, folder / "source.bin", folder / "preview.webp"
                    )
                    asset = asset.model_copy(update={"width": width, "height": height})
                else:
                    asset = await self.process_video(asset)
                await self.update(asset, status="ready", phase="处理完成", progress=100)
        except asyncio.CancelledError:
            asset = await self.get(asset_id)
            await self.update(
                asset,
                status="failed",
                phase="处理中断",
                error_message="服务已重启或任务中断，请重试处理；旧封面未改变",
                retryable=True,
            )
            raise
        except Exception as exc:
            asset = await self.get(asset_id)
            message = (
                str(exc)
                if isinstance(exc, (PlatformSkillError, MediaProcessingError))
                else "素材处理失败，请检查文件或重试"
            )
            await self.update(
                asset, status="failed", phase="处理失败", error_message=message, retryable=True
            )

    async def retry(self, asset_id):
        async with self.lock:
            asset = await self.get(asset_id)
            if asset.status != "failed" or asset.parent_asset_id:
                return asset
            # A failure can be observed just before the previous task exits.
            previous = self.tasks.get(asset_id)
            if previous is not None and not previous.done():
                await asyncio.gather(previous, return_exceptions=True)
            asset = await self.update(
                asset, status="uploaded", phase="等待处理", progress=0, error_message=None
            )
            self.schedule(asset.id)
            return asset

    async def presentation(self, skill_id):
        skill = await self.catalog.get_platform_skill(skill_id)
        ids = {
            value
            for item in skill.presentation.items
            for value in (item.image_asset_id, item.video_asset_id)
            if value
        }
        assets = [await self.get(asset_id) for asset_id in ids]
        return {
            "presentation": skill.presentation,
            "assets": assets,
            "fallback_cover_url": skill.cover_url,
        }

    async def save(self, skill_id, payload):
        await self.catalog.get_platform_skill(skill_id)
        items = []
        for item in payload.items:
            poster_id = None
            for asset_id, kind in ((item.image_asset_id, "image"), (item.video_asset_id, "video")):
                if not asset_id:
                    continue
                asset = await self.get(asset_id)
                if asset.skill_id != skill_id or asset.kind != kind:
                    raise _fail("media_binding_invalid", "封面素材类型或所属 Skill 不匹配")
                if asset.status != "ready":
                    raise _fail("media_not_ready", "请等待素材处理成功后再保存", 409)
                await self.content(asset.id, admin=True)
                if kind == "video":
                    poster_id = asset.poster_asset_id
                    if not poster_id:
                        raise _fail("media_poster_missing", "视频首帧尚未准备好，请重新处理", 409)
                    poster = await self.get(poster_id)
                    if poster.parent_asset_id != asset.id or poster.skill_id != skill_id:
                        raise _fail("media_poster_invalid", "视频首帧与素材不匹配", 409)
                    await self.content(poster_id, admin=True)
            items.append(PresentationItem(**item.model_dump(), poster_asset_id=poster_id))
        presentation = SkillPresentation(primary_item_id=payload.primary_item_id, items=items)
        return await self.catalog.save_presentation(
            skill_id, presentation, payload.expected_revision
        )

    async def content(self, asset_id, *, admin=False):
        asset = await self.get(asset_id)
        if not admin and not await self.catalog.is_presentation_asset_published(
            asset.skill_id, asset.id
        ):
            raise _fail("skill_media_not_found", "封面素材不存在或尚未发布", 404)
        path = self.folder(asset.id) / ("preview.mp4" if asset.kind == "video" else "preview.webp")
        if asset.status != "ready" or not path.is_file():
            raise _fail("skill_media_not_ready", "封面素材暂不可用", 404)
        return path, "video/mp4" if asset.kind == "video" else "image/webp"

    async def recover(self):
        if not self.root.is_dir():
            return
        for path in await asyncio.to_thread(lambda: list(self.root.glob("*/asset.json"))):
            try:
                asset = await self.get(UUID(path.parent.name))
                if asset.status in {"uploaded", "processing"}:
                    await self.update(
                        asset,
                        status="failed",
                        phase="处理中断",
                        error_message="上次处理因服务中断而停止，请重试；旧封面未改变",
                        retryable=True,
                    )
            except (ValueError, OSError):
                continue

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
