from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class PlatformKind(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"


class PlatformConnectionSource(StrEnum):
    NETSCAPE_FILE = "netscape_file"
    BROWSER_PROFILE = "browser_profile"


class PlatformUsageStrategy(StrEnum):
    ON_AUTH_REQUIRED = "on_auth_required"
    ALWAYS = "always"
    DISABLED = "disabled"


class PlatformConnectionHealth(StrEnum):
    UNCONFIGURED = "unconfigured"
    NEEDS_VALIDATION = "needs_validation"
    READY = "ready"
    VALID = "valid"
    EXPIRED = "expired"
    ERROR = "error"


class SupportedBrowser(StrEnum):
    CHROME = "chrome"
    EDGE = "edge"
    FIREFOX = "firefox"
    BRAVE = "brave"


PLATFORM_LABELS = {
    PlatformKind.DOUYIN: "抖音",
    PlatformKind.XIAOHONGSHU: "小红书",
}


class PlatformConnection(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    device_id: UUID
    platform: PlatformKind
    source: PlatformConnectionSource
    usage_strategy: PlatformUsageStrategy = PlatformUsageStrategy.ON_AUTH_REQUIRED
    browser: SupportedBrowser | None = None
    browser_profile_key: str | None = Field(default=None, max_length=240)
    browser_profile_label: str | None = Field(default=None, max_length=240)
    cookie_count: int = Field(default=0, ge=0)
    session_cookie_count: int = Field(default=0, ge=0)
    earliest_expiry_at: datetime | None = None
    health: PlatformConnectionHealth = PlatformConnectionHealth.NEEDS_VALIDATION
    last_validated_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=120)
    last_error_message: str | None = Field(default=None, max_length=300)
    legacy_imported: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PlatformConnectionState(BaseModel):
    schema_version: int = 1
    connections: list[PlatformConnection] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class PlatformConnectionSummary(BaseModel):
    platform: PlatformKind
    label: str
    configured: bool = False
    source: PlatformConnectionSource | None = None
    usage_strategy: PlatformUsageStrategy = PlatformUsageStrategy.ON_AUTH_REQUIRED
    browser: SupportedBrowser | None = None
    browser_profile_key: str | None = None
    browser_profile_label: str | None = None
    cookie_count: int = Field(default=0, ge=0)
    session_cookie_count: int = Field(default=0, ge=0)
    earliest_expiry_at: datetime | None = None
    health: PlatformConnectionHealth = PlatformConnectionHealth.UNCONFIGURED
    last_validated_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    legacy_imported: bool = False
    local_only: bool = True
    secure_store_available: bool = True


class PlatformConnectionListResponse(BaseModel):
    account_id: UUID
    device_id: UUID
    device_name: str
    local_only: bool = True
    items: list[PlatformConnectionSummary]


class BrowserProfileSummary(BaseModel):
    key: str = Field(min_length=1, max_length=240)
    label: str = Field(min_length=1, max_length=240)
    most_recent: bool = False


class BrowserInstallSummary(BaseModel):
    browser: SupportedBrowser
    label: str
    installed: bool
    profiles: list[BrowserProfileSummary] = Field(default_factory=list)


class BrowserDiscoveryResponse(BaseModel):
    browsers: list[BrowserInstallSummary]


class PlatformBrowserConnectionUpdate(BaseModel):
    browser: SupportedBrowser
    profile_key: str = Field(min_length=1, max_length=240)
    usage_strategy: PlatformUsageStrategy = PlatformUsageStrategy.ON_AUTH_REQUIRED
    consent_confirmed: bool = False

    @field_validator("profile_key")
    @classmethod
    def normalize_profile_key(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized or any(character in normalized for character in ("\x00", "\r", "\n")):
            raise ValueError("浏览器用户配置无效")
        return normalized


class PlatformConnectionStrategyUpdate(BaseModel):
    usage_strategy: PlatformUsageStrategy


class PlatformConnectionValidationRequest(BaseModel):
    test_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def normalize_url(self) -> PlatformConnectionValidationRequest:
        if self.test_url is not None:
            normalized = self.test_url.strip()
            self.test_url = normalized or None
        return self


class PlatformConnectionValidationResponse(BaseModel):
    connection: PlatformConnectionSummary
    message: str
    network_tested: bool = False


class CookieJarMetadata(BaseModel):
    cookie_count: int = Field(ge=0)
    session_cookie_count: int = Field(ge=0)
    earliest_expiry_at: datetime | None = None


class PlatformConnectionErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False
    platform: PlatformKind | None = None


PlatformValue = Literal["douyin", "xiaohongshu"]
