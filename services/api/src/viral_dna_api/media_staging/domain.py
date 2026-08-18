from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class MediaStagingProvider(StrEnum):
    DISABLED = "disabled"
    LOCAL_PROXY = "local_proxy"
    ALIYUN_OSS = "aliyun_oss"


class OssCredentialMode(StrEnum):
    ECS_RAM_ROLE = "ecs_ram_role"
    ACCESS_KEY = "access_key"


class MediaLeaseState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class MediaStagingConfig(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    provider: MediaStagingProvider = MediaStagingProvider.DISABLED
    credential_mode: OssCredentialMode = OssCredentialMode.ECS_RAM_ROLE
    region: str = Field(default="oss-cn-shanghai", min_length=1, max_length=80)
    bucket: str = Field(default="", max_length=255)
    internal_endpoint: str | None = Field(default=None, max_length=500)
    public_endpoint: str | None = Field(default=None, max_length=500)
    role_name: str | None = Field(default=None, max_length=128)
    object_prefix: str = Field(default="viraldna/staging", max_length=240)
    signed_url_ttl_seconds: int = Field(default=28_800, ge=900, le=32_400)
    cleanup_grace_seconds: int = Field(default=86_400, ge=0, le=2_592_000)
    multipart_threshold_bytes: int = Field(
        default=32 * 1024 * 1024,
        ge=5 * 1024 * 1024,
        le=5 * 1024 * 1024 * 1024,
    )
    upload_concurrency: int = Field(default=3, ge=1, le=16)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("object_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        return value.strip().strip("/") or "viraldna/staging"


class MediaStagingSettingsUpdate(BaseModel):
    provider: MediaStagingProvider = MediaStagingProvider.DISABLED
    credential_mode: OssCredentialMode = OssCredentialMode.ECS_RAM_ROLE
    region: str = Field(default="oss-cn-shanghai", min_length=1, max_length=80)
    bucket: str = Field(default="", max_length=255)
    internal_endpoint: str | None = Field(default=None, max_length=500)
    public_endpoint: str | None = Field(default=None, max_length=500)
    role_name: str | None = Field(default=None, max_length=128)
    object_prefix: str = Field(default="viraldna/staging", max_length=240)
    signed_url_ttl_seconds: int = Field(default=28_800, ge=900, le=32_400)
    cleanup_grace_seconds: int = Field(default=86_400, ge=0, le=2_592_000)
    access_key_id: SecretStr | None = Field(default=None, max_length=256)
    access_key_secret: SecretStr | None = Field(default=None, max_length=512)
    clear_access_key: bool = False

    @model_validator(mode="after")
    def validate_provider_fields(self) -> MediaStagingSettingsUpdate:
        if self.provider != MediaStagingProvider.ALIYUN_OSS:
            return self
        if not self.bucket.strip():
            raise ValueError("使用阿里云 OSS 时必须填写 Bucket")
        if self.credential_mode == OssCredentialMode.ACCESS_KEY:
            supplied = bool(self.access_key_id and self.access_key_secret)
            if bool(self.access_key_id) != bool(self.access_key_secret):
                raise ValueError("AccessKey ID 和 AccessKey Secret 必须同时填写")
            if self.clear_access_key and supplied:
                raise ValueError("不能同时清除并填写 AccessKey")
        return self


class MediaStagingSettingsResponse(BaseModel):
    provider: MediaStagingProvider
    credential_mode: OssCredentialMode
    region: str
    bucket: str
    internal_endpoint: str | None = None
    public_endpoint: str | None = None
    role_name: str | None = None
    object_prefix: str
    signed_url_ttl_seconds: int
    cleanup_grace_seconds: int
    access_key_configured: bool = False
    access_key_hint: str | None = None
    ready: bool = False
    validation_status: str = "not_configured"
    validation_message: str | None = None
    updated_at: datetime | None = None


class MediaAccessLease(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    workspace_id: UUID
    storage_object_id: UUID
    replica_id: UUID | None = None
    provider: MediaStagingProvider
    object_key: str = Field(min_length=1, max_length=1024)
    purpose: str = Field(default="video_generation", min_length=1, max_length=120)
    state: MediaLeaseState = MediaLeaseState.ACTIVE
    expires_at: datetime
    delete_after: datetime
    created_at: datetime = Field(default_factory=utc_now)
    revoked_at: datetime | None = None


class StagedMedia(BaseModel):
    storage_object_id: UUID
    lease_id: UUID | None = None
    provider: MediaStagingProvider
    url: str
    expires_at: datetime
    object_key: str
    reused_replica: bool = False


class MediaStagingValidationResponse(BaseModel):
    valid: bool
    message: str
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
