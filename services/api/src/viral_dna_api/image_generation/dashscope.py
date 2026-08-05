from __future__ import annotations

import asyncio
import base64
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..models import GenerationCostSource
from .contracts import (
    MAX_GENERATED_IMAGE_BYTES,
    AdapterIdentity,
    AdapterRequest,
    AdapterResult,
    GeneratedImage,
    ImageGenerationError,
)

MAX_INPUT_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_INPUT_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
}


def _image_data_url(path: Path) -> str:
    if not path.is_file():
        raise ImageGenerationError(409, "image_input_missing", "图片生成输入文件不存在")
    size = path.stat().st_size
    if size <= 0 or size > MAX_INPUT_IMAGE_BYTES:
        raise ImageGenerationError(
            422,
            "image_input_too_large",
            "百炼单张输入图片不能超过 10 MB",
        )
    media_type = mimetypes.guess_type(path.name)[0] or ""
    if media_type not in SUPPORTED_INPUT_MIME_TYPES:
        try:
            with Image.open(path) as source:
                media_type = Image.MIME.get(str(source.format or "").upper(), "")
        except (OSError, UnidentifiedImageError) as exc:
            raise ImageGenerationError(422, "image_input_invalid", "图片生成输入文件无效") from exc
    if media_type not in SUPPORTED_INPUT_MIME_TYPES:
        raise ImageGenerationError(422, "image_input_format", "百炼不支持该输入图片格式")
    payload = path.read_bytes()
    return f"data:{media_type};base64,{base64.b64encode(payload).decode('ascii')}"


def _safe_result_url(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise ImageGenerationError(
            502,
            "remote_image_url_invalid",
            "百炼返回了无效图片地址",
        ) from exc
    hostname = (parts.hostname or "").lower()
    if (
        parts.scheme.lower() != "https"
        or not hostname.endswith(".aliyuncs.com")
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
    ):
        raise ImageGenerationError(
            502,
            "remote_image_url_untrusted",
            "百炼返回的图片地址不在受信任的阿里云域名中",
        )
    return raw


def _validated_generated_image(payload: bytes, source_url: str) -> GeneratedImage:
    if not payload or len(payload) > MAX_GENERATED_IMAGE_BYTES:
        raise ImageGenerationError(502, "remote_image_size", "百炼返回的图片体积无效")
    try:
        with Image.open(BytesIO(payload)) as source:
            source.verify()
        with Image.open(BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            image_format = str(source.format or "").upper()
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageGenerationError(
            502,
            "remote_image_invalid",
            "百炼返回的文件不是有效图片",
        ) from exc
    media_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }.get(image_format)
    if media_type is None:
        raise ImageGenerationError(502, "remote_image_format", "百炼返回的图片格式不受支持")
    return GeneratedImage(
        payload=payload,
        media_type=media_type,
        width=width,
        height=height,
        metadata={"provider_result_url_host": urlsplit(source_url).hostname},
    )


def _provider_error(response: httpx.Response) -> ImageGenerationError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = str(payload.get("code") or f"http_{response.status_code}")[:120]
    message = str(payload.get("message") or "百炼图片生成请求失败")[:1000]
    lowered = f"{code} {message}".lower()
    if response.status_code in {401, 403}:
        return ImageGenerationError(
            422,
            "remote_auth_invalid",
            "百炼 API Key 无效、区域不匹配或没有图片模型权限",
        )
    if response.status_code == 404:
        return ImageGenerationError(
            422,
            "remote_model_unavailable",
            "所选图片模型在当前百炼区域不可用",
        )
    if response.status_code == 429:
        return ImageGenerationError(
            429,
            "remote_rate_limited",
            "百炼图片模型额度不足或请求过于频繁，请稍后重试",
            retryable=True,
        )
    if any(token in lowered for token in ("inspection", "content", "safety", "sensitive")):
        return ImageGenerationError(
            422,
            "remote_content_safety",
            f"图片请求未通过百炼内容安全检查：{message}",
        )
    if response.status_code >= 500:
        return ImageGenerationError(
            503,
            "remote_service_unavailable",
            f"百炼图片服务暂时不可用：{message}",
            retryable=True,
        )
    return ImageGenerationError(422, code, f"百炼图片生成失败：{message}")


class DashScopeQwenImageAdapter:
    def __init__(
        self,
        *,
        identity: AdapterIdentity,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 300,
        max_attempts: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        download_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.identity = identity
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, min(3, max_attempts))
        self.transport = transport
        self.download_transport = download_transport

    async def generate(self, request: AdapterRequest) -> AdapterResult:
        paths = [
            *([request.source_path] if request.source_path is not None else []),
            *(item.path for item in request.references),
        ]
        if len(paths) > self.identity.capability.max_input_images:
            raise ImageGenerationError(
                422,
                "remote_reference_limit",
                (
                    f"{self.identity.model} 最多接收 "
                    f"{self.identity.capability.max_input_images} 张输入图；"
                    f"当前共 {len(paths)} 张输入图"
                ),
            )
        content = [{"image": await asyncio.to_thread(_image_data_url, path)} for path in paths]
        content.append({"text": request.positive_prompt})
        parameters: dict[str, Any] = {
            "n": request.candidate_count,
            "negative_prompt": request.negative_prompt or " ",
            "prompt_extend": True,
            "watermark": False,
            "size": f"{request.width}*{request.height}",
        }
        if request.seed is not None:
            parameters["seed"] = request.seed
        body = {
            "model": self.identity.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }
        endpoint = f"{self.base_url}/services/aigc/multimodal-generation/generation"
        response: httpx.Response | None = None
        timeout = httpx.Timeout(self.timeout_seconds, connect=20)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempt in range(self.max_attempts):
                try:
                    response = await client.post(
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt + 1 >= self.max_attempts:
                        raise ImageGenerationError(
                            503,
                            "remote_transport_error",
                            "无法连接百炼图片服务，请稍后重试",
                            retryable=True,
                        ) from exc
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code < 400:
                    break
                error = _provider_error(response)
                if error.retryable and attempt + 1 < self.max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise error
        if response is None:
            raise ImageGenerationError(503, "remote_no_response", "百炼图片服务没有返回结果")
        try:
            payload = response.json()
            output = payload["output"]
            choices = output["choices"]
            raw_content = choices[0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ImageGenerationError(
                502,
                "remote_response_invalid",
                "百炼图片服务返回格式不完整",
            ) from exc
        urls = [
            _safe_result_url(item.get("image"))
            for item in raw_content
            if isinstance(item, dict) and item.get("image")
        ]
        if not urls or len(urls) > request.candidate_count:
            raise ImageGenerationError(
                502,
                "remote_candidates_invalid",
                "百炼返回的候选数量无效",
            )
        images = await asyncio.gather(*(self._download_image(url) for url in urls))
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        usage = {
            **usage,
            "requested_image_count": request.candidate_count,
            "downloaded_image_count": len(images),
        }
        unit_cost = self.identity.model_option.unit_cost_micros if self.identity.model_option else 0
        return AdapterResult(
            images=tuple(images),
            provider_request_id=str(payload.get("request_id") or "")[:300] or None,
            usage=usage,
            actual_cost_micros=unit_cost * len(images),
            cost_source=GenerationCostSource.CONFIGURED_RATE,
        )

    async def _download_image(self, url: str) -> GeneratedImage:
        timeout = httpx.Timeout(self.timeout_seconds, connect=20)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=self.download_transport,
        ) as client:
            try:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    final_url = _safe_result_url(str(response.url))
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_GENERATED_IMAGE_BYTES:
                        raise ImageGenerationError(
                            502,
                            "remote_image_size",
                            "百炼返回的图片体积超过限制",
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_GENERATED_IMAGE_BYTES:
                            raise ImageGenerationError(
                                502,
                                "remote_image_size",
                                "百炼返回的图片体积超过限制",
                            )
                        chunks.append(chunk)
            except ImageGenerationError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise ImageGenerationError(
                    502,
                    "remote_image_download_failed",
                    "百炼已生成图片，但下载到工作区失败",
                    retryable=True,
                ) from exc
        return _validated_generated_image(b"".join(chunks), final_url)
