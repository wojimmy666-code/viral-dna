from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from viral_dna_api.media_staging.domain import (
    MediaStagingConfig,
    MediaStagingProvider,
    MediaStagingSettingsUpdate,
    OssCredentialMode,
)
from viral_dna_api.media_staging.oss import AliyunOssClient
from viral_dna_api.media_staging.service import MediaStagingService
from viral_dna_api.storage_objects import StorageManager, StorageObject, StorageObjectType
from viral_dna_api.video_generation.errors import classify_video_provider_failure


def oss_config() -> MediaStagingConfig:
    return MediaStagingConfig(
        account_id=uuid4(),
        provider=MediaStagingProvider.ALIYUN_OSS,
        credential_mode=OssCredentialMode.ACCESS_KEY,
        region="oss-cn-shanghai",
        bucket="viraldna-test",
        object_prefix="viraldna/staging",
    )


def test_media_staging_settings_require_complete_access_key_pair() -> None:
    with pytest.raises(ValidationError):
        MediaStagingSettingsUpdate(
            provider=MediaStagingProvider.ALIYUN_OSS,
            credential_mode=OssCredentialMode.ACCESS_KEY,
            region="oss-cn-shanghai",
            bucket="viraldna-test",
            access_key_id="key-only",
        )


def test_media_staging_signed_url_ttl_respects_oss_v1_limit() -> None:
    with pytest.raises(ValidationError):
        MediaStagingSettingsUpdate(
            provider=MediaStagingProvider.ALIYUN_OSS,
            bucket="viraldna-test",
            signed_url_ttl_seconds=32_401,
        )


@pytest.mark.asyncio
async def test_media_staging_reuses_existing_local_storage_object(tmp_path: Path) -> None:
    payload = b"existing-depth-video"
    source_path = tmp_path / "depth.mp4"
    source_path.write_bytes(payload)
    account_id = uuid4()
    workspace_id = uuid4()
    storage_object = StorageObject(
        account_id=account_id,
        workspace_id=workspace_id,
        object_type=StorageObjectType.DEPTH_VIDEO,
        original_filename=source_path.name,
        mime_type="video/mp4",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    repository = SimpleNamespace(
        list_storage_objects=AsyncMock(return_value=[storage_object]),
    )
    account_context = SimpleNamespace(
        ensure_current=AsyncMock(
            return_value=SimpleNamespace(
                account=SimpleNamespace(id=account_id),
                active_workspace=SimpleNamespace(id=workspace_id),
                storage_locations=[],
            )
        )
    )
    storage = Mock(spec=StorageManager)
    storage.materialize_local = AsyncMock(return_value=source_path)
    storage.register_existing_local_object = AsyncMock()
    service = MediaStagingService(
        repository=repository,
        workspace=SimpleNamespace(root=tmp_path),
        account_context=account_context,
        storage=storage,
        public_media=Mock(),
        secret_store=Mock(),
    )

    result = await service._ensure_storage_object(
        source_path,
        object_type=StorageObjectType.DEPTH_VIDEO,
        expected_sha256=storage_object.sha256,
    )

    assert result is storage_object
    storage.materialize_local.assert_awaited_once_with(storage_object.id)
    storage.register_existing_local_object.assert_not_awaited()


def test_media_staging_failure_is_not_reported_as_provider_failure() -> None:
    failure = classify_video_provider_failure(
        provider="volc_ark",
        code="oss_upload_network_failed",
        message="upload connection failed",
    )

    assert failure.category == "media_staging"
    assert failure.title == "媒体暂存未完成"
    assert failure.suggested_action == "retry"
    assert failure.retryable is True


def test_missing_media_staging_configuration_points_to_settings() -> None:
    failure = classify_video_provider_failure(
        provider="volc_ark",
        code="media_staging_not_configured",
        message="OSS is not configured",
    )

    assert failure.category == "media_staging"
    assert failure.title == "媒体暂存服务尚未配置"
    assert failure.suggested_action == "open_model_settings"


@pytest.mark.asyncio
async def test_oss_presign_uses_public_endpoint_and_hides_secret() -> None:
    config = oss_config().model_copy(
        update={
            "internal_endpoint": "https://oss-cn-shanghai-internal.aliyuncs.com",
            "public_endpoint": "https://oss-cn-shanghai.aliyuncs.com",
        }
    )
    client = AliyunOssClient(config, access_key=("test-key-id", "super-secret"))
    try:
        url, expires_at = await client.presign_get("viraldna/staging/example.mp4", 900)
    finally:
        await client.close()
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "viraldna-test.oss-cn-shanghai.aliyuncs.com"
    assert query["OSSAccessKeyId"] == ["test-key-id"]
    assert "Signature" in query
    assert "super-secret" not in url
    assert expires_at.tzinfo is not None


@pytest.mark.asyncio
async def test_oss_validation_covers_upload_read_and_delete() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            return httpx.Response(200, headers={"etag": '"probe-etag"'})
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(206, content=b"v")
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(405)

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = AliyunOssClient(
        oss_config(),
        access_key=("test-key-id", "super-secret"),
        client=http_client,
    )
    try:
        valid, message, latency_ms = await client.validate()
    finally:
        await http_client.aclose()
    assert valid is True
    assert "上传" in message
    assert latency_ms >= 0
    assert methods == ["PUT", "HEAD", "GET", "DELETE"]
