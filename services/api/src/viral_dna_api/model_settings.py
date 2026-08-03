from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .ai.catalog import ModelCatalog, ModelCatalogError, load_model_catalog
from .ai.contracts import ModelProviderError, ModelProviderUnavailable
from .ai.providers.dashscope import (
    DEFAULT_BASE_URL,
    CredentialValidationResult,
    DashScopeProvider,
)
from .models import (
    ModelOption,
    ModelProviderOption,
    ModelSettingsResponse,
    ModelSettingsUpdate,
)
from .runtime_config import RuntimeConfigError, get_config_value, persist_config_values

DEFAULT_MODEL_ALIAS = "auto"
SUPPORTED_PROVIDER = "dashscope"
ALLOWED_DASHSCOPE_HOSTS = {
    "dashscope.aliyuncs.com",
    "dashscope-intl.aliyuncs.com",
    "dashscope-us.aliyuncs.com",
}


class CredentialValidator(Protocol):
    async def validate_credentials(self, model: str) -> CredentialValidationResult: ...


ProviderFactory = Callable[[str, str], CredentialValidator]


class ModelSettingsServiceError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _default_provider_factory(api_key: str, base_url: str) -> CredentialValidator:
    return DashScopeProvider(api_key=api_key, base_url=base_url)


def _mask_api_key(api_key: str) -> str | None:
    stripped = api_key.strip()
    if not stripped:
        return None
    suffix = stripped[-4:] if len(stripped) >= 4 else stripped
    return f"••••••••{suffix}"


def _parse_validation_time(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_dashscope_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ModelSettingsServiceError(422, "模型服务地址格式无效") from exc
    hostname = (parts.hostname or "").lower()
    if (
        parts.scheme.lower() != "https"
        or hostname not in ALLOWED_DASHSCOPE_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in {None, 443}
        or parts.query
        or parts.fragment
    ):
        raise ModelSettingsServiceError(
            422,
            "为保护 API Key，模型服务地址仅允许官方 DashScope HTTPS 接口",
        )
    path = parts.path.rstrip("/")
    if path != "/compatible-mode/v1":
        raise ModelSettingsServiceError(422, "当前仅支持 DashScope OpenAI 兼容接口")
    return urlunsplit(("https", hostname, path, "", ""))


class ModelSettingsService:
    def __init__(self, provider_factory: ProviderFactory | None = None) -> None:
        self._provider_factory = provider_factory or _default_provider_factory

    def get(self, *, validation_latency_ms: int | None = None) -> ModelSettingsResponse:
        try:
            catalog = load_model_catalog()
        except ModelCatalogError as exc:
            raise ModelSettingsServiceError(503, str(exc)) from exc

        provider = get_config_value("VIRAL_DNA_VLM_PROVIDER", SUPPORTED_PROVIDER).strip()
        if provider != SUPPORTED_PROVIDER:
            provider = SUPPORTED_PROVIDER
        model_alias = (
            get_config_value("VIRAL_DNA_VLM_MODEL_ALIAS", DEFAULT_MODEL_ALIAS).strip()
            or DEFAULT_MODEL_ALIAS
        )
        options = catalog.model_options(provider)
        selected = self._select_model(catalog, provider, model_alias, options)
        api_key = get_config_value("DASHSCOPE_API_KEY", "")
        base_url = get_config_value("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL).strip()
        try:
            normalized_base_url = _normalize_dashscope_base_url(base_url)
        except ModelSettingsServiceError:
            normalized_base_url = DEFAULT_BASE_URL

        return ModelSettingsResponse(
            provider=provider,
            model_alias=model_alias if model_alias == DEFAULT_MODEL_ALIAS else selected.alias,
            model=selected.model,
            base_url=normalized_base_url,
            api_key_configured=bool(api_key.strip()),
            api_key_hint=_mask_api_key(api_key),
            last_validated_at=_parse_validation_time(
                get_config_value("VIRAL_DNA_MODEL_LAST_VALIDATED_AT", "")
            ),
            validation_latency_ms=validation_latency_ms,
            catalog_version=catalog.catalog_version,
            pricing_version=catalog.pricing_version,
            providers=[
                ModelProviderOption(
                    id=SUPPORTED_PROVIDER,
                    label="阿里云百炼（DashScope）",
                    base_url=DEFAULT_BASE_URL,
                )
            ],
            models=options,
        )

    async def update(self, payload: ModelSettingsUpdate) -> ModelSettingsResponse:
        provider = payload.provider.strip().lower()
        if provider != SUPPORTED_PROVIDER:
            raise ModelSettingsServiceError(422, "当前版本仅支持阿里云百炼")

        try:
            catalog = load_model_catalog()
        except ModelCatalogError as exc:
            raise ModelSettingsServiceError(503, str(exc)) from exc
        options = catalog.model_options(provider)
        selected = self._select_model(catalog, provider, payload.model_alias, options)

        supplied_key = payload.api_key.get_secret_value().strip() if payload.api_key else ""
        api_key = supplied_key or get_config_value("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise ModelSettingsServiceError(422, "请填写阿里云百炼 API Key")

        requested_base_url = (
            str(payload.base_url)
            if payload.base_url is not None
            else get_config_value("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL)
        )
        base_url = _normalize_dashscope_base_url(requested_base_url)
        validator = self._provider_factory(api_key, base_url)
        try:
            validation = await validator.validate_credentials(selected.model)
        except ModelProviderUnavailable as exc:
            raise ModelSettingsServiceError(422, "请填写有效的阿里云百炼 API Key") from exc
        except ModelProviderError as exc:
            raise self._translate_provider_error(exc) from exc

        validated_at = datetime.now(UTC).isoformat()
        try:
            persist_config_values(
                {
                    "VIRAL_DNA_VLM_PROVIDER": provider,
                    "VIRAL_DNA_VLM_MODEL_ALIAS": payload.model_alias,
                    "DASHSCOPE_API_KEY": api_key,
                    "DASHSCOPE_BASE_URL": base_url,
                    "VIRAL_DNA_MODEL_LAST_VALIDATED_AT": validated_at,
                }
            )
        except RuntimeConfigError as exc:
            raise ModelSettingsServiceError(500, "API Key 已验证，但本地配置保存失败") from exc
        return self.get(validation_latency_ms=validation.latency_ms)

    @staticmethod
    def _select_model(
        catalog: ModelCatalog,
        provider: str,
        alias: str,
        options: list[ModelOption],
    ) -> ModelOption:
        normalized_alias = alias.strip() or DEFAULT_MODEL_ALIAS
        if not options:
            raise ModelSettingsServiceError(503, "模型目录中没有可用的阿里云百炼模型")
        if normalized_alias == DEFAULT_MODEL_ALIAS:
            return options[0]
        try:
            selected = catalog.model_option(normalized_alias)
        except ModelCatalogError as exc:
            raise ModelSettingsServiceError(422, "所选模型不在当前模型目录中") from exc
        if selected.provider != provider:
            raise ModelSettingsServiceError(422, "所选模型与 Provider 不匹配")
        return selected

    @staticmethod
    def _translate_provider_error(error: ModelProviderError) -> ModelSettingsServiceError:
        if error.status_code in {401, 403}:
            return ModelSettingsServiceError(422, "API Key 无效，或没有访问所选模型的权限")
        if error.status_code == 404:
            return ModelSettingsServiceError(422, "所选模型在当前百炼区域不可用")
        if error.status_code == 429:
            return ModelSettingsServiceError(429, "百炼额度不足或请求过于频繁，请检查账户后重试")
        if error.retryable or error.code in {"model_timeout", "model_transport_error"}:
            return ModelSettingsServiceError(503, "暂时无法连接百炼服务，请稍后重试")
        return ModelSettingsServiceError(422, "模型连接校验失败，请检查 Key、区域和模型权限")
