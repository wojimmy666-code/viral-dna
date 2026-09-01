from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from ..managed_assets.service import (
    ACCESS_KEY_ENV as MANAGED_ASSET_ACCESS_KEY_ENV,
)
from ..managed_assets.service import (
    PROJECT_ENV as MANAGED_ASSET_PROJECT_ENV,
)
from ..managed_assets.service import (
    REGION_ENV as MANAGED_ASSET_REGION_ENV,
)
from ..managed_assets.service import (
    SECRET_KEY_ENV as MANAGED_ASSET_SECRET_KEY_ENV,
)
from ..managed_assets.service import (
    VALIDATED_ENV as MANAGED_ASSET_VALIDATED_ENV,
)
from ..managed_assets.service import (
    ManagedAssetCatalogService,
    ManagedAssetServiceError,
)
from ..models import (
    VideoCostEstimateRequest,
    VideoCostEstimateResponse,
    VideoGenerationSettingsResponse,
    VideoGenerationSettingsUpdate,
    VideoProviderSettingsResponse,
    VideoProviderValidationRequest,
    VideoProviderValidationResponse,
)
from ..public_media import (
    PUBLIC_MEDIA_BASE_URL_ENV,
    PUBLIC_MEDIA_TTL_SECONDS_ENV,
    PublicMediaStagingError,
    normalize_public_media_base_url,
    public_media_configuration,
)
from ..runtime_config import RuntimeConfigError, get_config_value, persist_config_values
from .catalog import (
    VideoModelCatalogError,
    load_video_model_catalog,
    video_duration_constraint_text,
    video_duration_is_supported,
)
from .costing import estimate_video_cost
from .registry import VideoProviderRegistry, VideoProviderRegistryError

DEFAULT_VIDEO_MODEL_ALIAS = "bailian_wan_2_7_r2v"
LEGACY_VIDEO_MODEL_ALIASES = {
    "bailian_wan_2_7_i2v": DEFAULT_VIDEO_MODEL_ALIAS,
}
DEFAULT_BASE_URLS = {
    "bailian": "https://dashscope.aliyuncs.com/api/v1",
    "volc_ark": "https://ark.cn-beijing.volces.com/api/v3",
    "minimax": "https://api.minimaxi.com/v1",
    "gemini_omni": "https://generativelanguage.googleapis.com/v1beta",
}
PROVIDER_LABELS = {
    "bailian": "阿里云百炼",
    "volc_ark": "火山方舟 Seedance",
    "minimax": "MiniMax",
    "gemini_omni": "Google Gemini Omni",
}
KEY_ENV = {
    "bailian": "DASHSCOPE_API_KEY",
    "volc_ark": "ARK_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "gemini_omni": "GEMINI_API_KEY",
}
BASE_ENV = {
    "bailian": "DASHSCOPE_VIDEO_BASE_URL",
    "volc_ark": "ARK_VIDEO_BASE_URL",
    "minimax": "MINIMAX_VIDEO_BASE_URL",
    "gemini_omni": "GEMINI_OMNI_BASE_URL",
}
VALIDATED_ENV = {
    "bailian": "VIRAL_DNA_VIDEO_BAILIAN_VALIDATED_AT",
    "volc_ark": "VIRAL_DNA_VIDEO_VOLC_ARK_VALIDATED_AT",
    "minimax": "VIRAL_DNA_VIDEO_MINIMAX_VALIDATED_AT",
    "gemini_omni": "VIRAL_DNA_VIDEO_GEMINI_OMNI_VALIDATED_AT",
}

VALIDATION_ERROR_STATUS = {
    "video_provider_auth_invalid": 401,
    "video_provider_permission_denied": 403,
    "video_provider_balance_insufficient": 402,
    "video_provider_rate_limited": 429,
    "video_provider_unavailable": 503,
    "video_provider_response_invalid": 502,
    "video_provider_request_failed": 502,
}


class VideoGenerationSettingsServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> VideoGenerationSettingsServiceError:
    return VideoGenerationSettingsServiceError(status_code, code, message)


def _mask(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    suffix = stripped[-4:] if len(stripped) >= 4 else stripped
    return f"••••••••{suffix}"


def _parse_time(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def normalize_provider_base_url(provider: str, value: str) -> str:
    raw = value.strip().rstrip("/")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise _fail(422, "video_endpoint_invalid", "视频 Provider 服务地址格式无效") from exc
    host = (parts.hostname or "").lower()
    allowed = False
    required_path = ""
    if provider == "bailian":
        allowed = host in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
        } or host.endswith(".maas.aliyuncs.com")
        required_path = "/api/v1"
    elif provider == "volc_ark":
        allowed = host in {"ark.cn-beijing.volces.com", "ark.cn-shanghai.volces.com"}
        required_path = "/api/v3"
    elif provider == "minimax":
        allowed = host in {"api.minimaxi.com", "api.minimax.io", "api.minimax.chat"}
        required_path = "/v1"
    elif provider == "gemini_omni":
        if host in {"localhost", "localhost.localdomain"} or host.endswith(
            (".localhost", ".local", ".internal", ".lan")
        ):
            allowed = False
        else:
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                allowed = bool(host and "." in host)
            else:
                allowed = address.is_global
        required_path = parts.path.rstrip("/") or "/v1beta"
    if (
        not allowed
        or parts.scheme.lower() != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or parts.query
        or parts.fragment
        or (provider != "gemini_omni" and parts.path.rstrip("/") != required_path)
        or (provider == "gemini_omni" and ".." in required_path.split("/"))
    ):
        raise _fail(
            422,
            "video_endpoint_not_allowed",
            (
                "Gemini Omni 只允许官方地址或公网 HTTPS 兼容中转地址"
                if provider == "gemini_omni"
                else "为保护 API Key，只允许对应 Provider 的官方 HTTPS 接口"
            ),
        )
    return urlunsplit(("https", parts.netloc, required_path, "", ""))


class VideoGenerationSettingsService:
    def __init__(
        self,
        registry: VideoProviderRegistry | None = None,
        managed_assets: ManagedAssetCatalogService | None = None,
    ) -> None:
        self.registry = registry or VideoProviderRegistry()
        self.managed_assets = managed_assets or ManagedAssetCatalogService()

    def api_key(self, provider: str) -> str:
        try:
            name = KEY_ENV[provider]
        except KeyError as exc:
            raise _fail(422, "video_provider_invalid", "未知的视频 Provider") from exc
        return get_config_value(name, "").strip()

    def base_url(self, provider: str) -> str:
        try:
            configured = get_config_value(BASE_ENV[provider], DEFAULT_BASE_URLS[provider])
            return normalize_provider_base_url(provider, configured)
        except KeyError as exc:
            raise _fail(422, "video_provider_invalid", "未知的视频 Provider") from exc

    def get(self) -> VideoGenerationSettingsResponse:
        catalog = load_video_model_catalog()
        public_media = public_media_configuration()
        alias = get_config_value(
            "VIRAL_DNA_VIDEO_DEFAULT_MODEL_ALIAS", DEFAULT_VIDEO_MODEL_ALIAS
        ).strip()
        alias = LEGACY_VIDEO_MODEL_ALIASES.get(alias, alias)
        try:
            selected = catalog.option(alias)
        except VideoModelCatalogError:
            alias = DEFAULT_VIDEO_MODEL_ALIAS
            selected = catalog.option(alias)
        resolution = get_config_value("VIRAL_DNA_VIDEO_DEFAULT_RESOLUTION", "720P").strip().upper()
        if resolution not in selected.capability.supported_resolutions:
            resolution = (
                "720P"
                if "720P" in selected.capability.supported_resolutions
                else selected.capability.supported_resolutions[0]
            )
        try:
            poll_interval = float(get_config_value("VIRAL_DNA_VIDEO_POLL_INTERVAL_SECONDS", "5"))
        except ValueError:
            poll_interval = 5
        try:
            timeout = int(get_config_value("VIRAL_DNA_VIDEO_TASK_TIMEOUT_SECONDS", "900"))
        except ValueError:
            timeout = 900
        provider_settings: list[VideoProviderSettingsResponse] = []
        managed_asset_status = self.managed_assets.status()
        for provider in ("bailian", "volc_ark", "minimax", "gemini_omni"):
            key = self.api_key(provider)
            validated_at = _parse_time(get_config_value(VALIDATED_ENV[provider], ""))
            provider_settings.append(
                VideoProviderSettingsResponse(
                    provider=provider,
                    label=PROVIDER_LABELS[provider],
                    api_key_configured=bool(key),
                    api_key_hint=_mask(key),
                    base_url=self.base_url(provider),
                    last_validated_at=validated_at,
                    validation_status=(
                        "valid" if key and validated_at else "unknown" if key else "not_configured"
                    ),
                    validation_message=(
                        "已校验"
                        if key and validated_at
                        else "尚未校验"
                        if key
                        else "未配置 API Key"
                    ),
                    managed_asset_catalog_supported=provider == "volc_ark",
                    managed_asset_credentials_configured=(
                        managed_asset_status.credentials_configured
                        if provider == "volc_ark"
                        else False
                    ),
                    managed_asset_access_key_hint=(
                        managed_asset_status.access_key_hint
                        if provider == "volc_ark"
                        else None
                    ),
                    managed_asset_region=(
                        managed_asset_status.region if provider == "volc_ark" else None
                    ),
                    managed_asset_project_name=(
                        managed_asset_status.project_name if provider == "volc_ark" else None
                    ),
                    managed_asset_validation_status=(
                        managed_asset_status.validation_status
                        if provider == "volc_ark"
                        else "not_supported"
                    ),
                    managed_asset_validation_message=(
                        managed_asset_status.validation_message
                        if provider == "volc_ark"
                        else None
                    ),
                )
            )
        return VideoGenerationSettingsResponse(
            enabled=get_config_value("VIRAL_DNA_VIDEO_GENERATION_ENABLED", "true").lower()
            == "true",
            default_model_alias=alias,
            default_resolution=resolution,
            poll_interval_seconds=min(60, max(0.2, poll_interval)),
            task_timeout_seconds=min(7200, max(30, timeout)),
            public_media_base_url=public_media.base_url,
            public_media_ttl_seconds=public_media.ttl_seconds,
            public_media_transport_ready=public_media.ready,
            public_media_validation_message=public_media.validation_message,
            catalog_version=catalog.catalog_version,
            pricing_version=catalog.pricing_version,
            providers=provider_settings,
            models=catalog.options(),
        )

    async def validate_provider(
        self,
        provider: str,
        payload: VideoProviderValidationRequest,
    ) -> VideoProviderValidationResponse:
        key = (
            payload.api_key.get_secret_value().strip()
            if payload.api_key is not None
            else self.api_key(provider)
        )
        if not key:
            raise _fail(422, "video_api_key_required", "请先填写该 Provider 的 API Key")
        base_url = normalize_provider_base_url(
            provider, payload.base_url or self.base_url(provider)
        )
        try:
            adapter = self.registry.get(provider)
        except VideoProviderRegistryError as exc:
            raise _fail(422, "video_provider_invalid", str(exc)) from exc
        result = await adapter.validate_credentials(key, base_url)
        if result.valid and payload.api_key is None:
            try:
                persist_config_values({VALIDATED_ENV[provider]: datetime.now(UTC).isoformat()})
            except RuntimeConfigError as exc:
                raise _fail(500, "video_settings_save_failed", str(exc)) from exc
        return VideoProviderValidationResponse(
            provider=provider,
            valid=result.valid,
            message=result.message,
            latency_ms=result.latency_ms,
            balance_known=result.balance_known,
            balance_micros=result.balance_micros,
            currency=result.currency,
            error_code=result.error_code,
            retryable=result.retryable,
        )

    async def update(
        self, payload: VideoGenerationSettingsUpdate
    ) -> VideoGenerationSettingsResponse:
        catalog = load_video_model_catalog()
        try:
            selected = catalog.option(payload.default_model_alias)
        except VideoModelCatalogError as exc:
            raise _fail(422, "video_model_invalid", str(exc)) from exc
        if not (
            selected.capability.multi_image_reference
            and selected.capability.ordered_reference_images
        ):
            raise _fail(
                422,
                "video_model_capability_unsupported",
                "当前创作流程只允许支持有序多图参考的视频模型",
            )
        if payload.default_resolution not in selected.capability.supported_resolutions:
            raise _fail(422, "video_resolution_unsupported", "默认分辨率不受所选视频模型支持")
        updates = {
            "VIRAL_DNA_VIDEO_GENERATION_ENABLED": "true" if payload.enabled else "false",
            "VIRAL_DNA_VIDEO_DEFAULT_MODEL_ALIAS": payload.default_model_alias,
            "VIRAL_DNA_VIDEO_DEFAULT_RESOLUTION": payload.default_resolution,
            "VIRAL_DNA_VIDEO_POLL_INTERVAL_SECONDS": str(payload.poll_interval_seconds),
            "VIRAL_DNA_VIDEO_TASK_TIMEOUT_SECONDS": str(payload.task_timeout_seconds),
        }
        if "public_media_base_url" in payload.model_fields_set:
            try:
                public_media_base_url = normalize_public_media_base_url(
                    payload.public_media_base_url
                )
            except PublicMediaStagingError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            updates[PUBLIC_MEDIA_BASE_URL_ENV] = public_media_base_url or ""
        if "public_media_ttl_seconds" in payload.model_fields_set:
            updates[PUBLIC_MEDIA_TTL_SECONDS_ENV] = str(payload.public_media_ttl_seconds)
        for item in payload.providers:
            base_url = normalize_provider_base_url(
                item.provider, item.base_url or self.base_url(item.provider)
            )
            updates[BASE_ENV[item.provider]] = base_url
            new_key = item.api_key.get_secret_value().strip() if item.api_key is not None else ""
            if item.clear_api_key:
                updates[KEY_ENV[item.provider]] = ""
                updates[VALIDATED_ENV[item.provider]] = ""
            elif not new_key:
                pass
            else:
                result = await self.validate_provider(
                    item.provider,
                    VideoProviderValidationRequest(api_key=new_key, base_url=base_url),
                )
                if not result.valid:
                    error_code = result.error_code or "video_api_key_invalid"
                    raise _fail(
                        VALIDATION_ERROR_STATUS.get(error_code, 502),
                        error_code,
                        result.message,
                    )
                updates[KEY_ENV[item.provider]] = new_key
                updates[VALIDATED_ENV[item.provider]] = datetime.now(UTC).isoformat()

            managed_fields = {
                "managed_asset_access_key",
                "managed_asset_secret_key",
                "managed_asset_region",
                "managed_asset_project_name",
                "clear_managed_asset_credentials",
            }
            if item.provider != "volc_ark" or not (item.model_fields_set & managed_fields):
                continue
            current_assets = self.managed_assets.settings()
            region = item.managed_asset_region or current_assets.region
            project_name = (
                item.managed_asset_project_name or current_assets.project_name
            ).strip()
            if item.clear_managed_asset_credentials:
                updates.update(
                    {
                        MANAGED_ASSET_ACCESS_KEY_ENV: "",
                        MANAGED_ASSET_SECRET_KEY_ENV: "",
                        MANAGED_ASSET_REGION_ENV: region,
                        MANAGED_ASSET_PROJECT_ENV: project_name,
                        MANAGED_ASSET_VALIDATED_ENV: "",
                    }
                )
                continue
            access_key = (
                item.managed_asset_access_key.get_secret_value().strip()
                if item.managed_asset_access_key is not None
                else current_assets.access_key
            )
            secret_key = (
                item.managed_asset_secret_key.get_secret_value().strip()
                if item.managed_asset_secret_key is not None
                else current_assets.secret_key
            )
            if bool(access_key) != bool(secret_key):
                raise _fail(
                    422,
                    "managed_asset_credentials_incomplete",
                    "火山方舟资产目录必须同时填写 Access Key 和 Secret Key",
                )
            proposed = self.managed_assets.proposed_settings(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                project_name=project_name,
            )
            try:
                if proposed.configured:
                    await self.managed_assets.validate_credentials(proposed)
            except ManagedAssetServiceError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            updates.update(
                {
                    MANAGED_ASSET_ACCESS_KEY_ENV: access_key,
                    MANAGED_ASSET_SECRET_KEY_ENV: secret_key,
                    MANAGED_ASSET_REGION_ENV: region,
                    MANAGED_ASSET_PROJECT_ENV: project_name,
                    MANAGED_ASSET_VALIDATED_ENV: (
                        datetime.now(UTC).isoformat() if proposed.configured else ""
                    ),
                }
            )
        try:
            persist_config_values(updates)
        except RuntimeConfigError as exc:
            raise _fail(500, "video_settings_save_failed", str(exc)) from exc
        return self.get()

    def estimate(self, payload: VideoCostEstimateRequest) -> VideoCostEstimateResponse:
        try:
            spec = load_video_model_catalog().option(payload.model_alias)
        except VideoModelCatalogError as exc:
            raise _fail(422, "video_model_invalid", str(exc)) from exc
        if payload.resolution not in spec.capability.supported_resolutions:
            raise _fail(
                422, "video_resolution_unsupported", f"{spec.label} 不支持 {payload.resolution}"
            )
        if not video_duration_is_supported(
            spec.capability,
            payload.duration_seconds,
        ):
            raise _fail(
                422,
                "video_duration_unsupported",
                f"{spec.label} {video_duration_constraint_text(spec.capability)}",
            )
        estimate = estimate_video_cost(
            spec,
            duration_seconds=payload.duration_seconds,
            resolution=payload.resolution,
            candidate_count=payload.candidate_count,
        )
        return VideoCostEstimateResponse(
            model_alias=spec.alias,
            provider=spec.provider,
            model=spec.model,
            duration_seconds=payload.duration_seconds,
            resolution=payload.resolution,
            candidate_count=payload.candidate_count,
            estimate_known=estimate.known,
            estimated_cost_micros=estimate.micros,
            pricing_version=estimate.pricing_version,
            explanation=estimate.explanation,
        )
