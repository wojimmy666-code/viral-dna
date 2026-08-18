from __future__ import annotations

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

