from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from ..ai.providers.dashscope import CredentialValidationResult, DashScopeProvider
from ..models import (
    GenerationCostSource,
    ImageExecutionMode,
    ImageGenerationCapability,
    ImageGenerationSettingsResponse,
    ImageGenerationSettingsUpdate,
    LocalCodexAutoConfigureRequest,
    LocalCodexDiscoveryResponse,
    LocalCodexNetworkTestRequest,
    LocalCodexNetworkTestResponse,
    LocalImageToolDetectRequest,
    LocalImageToolDetectResponse,
)
from ..runtime_config import RuntimeConfigError, get_config_value, persist_config_values
from .catalog import ImageModelCatalogError, load_image_model_catalog
from .codex_local import (
    CODEX_IMAGEGEN_ADAPTER_ID,
    CodexNetworkProbeResult,
    discover_codex_environment,
    probe_codex_network,
    resolve_codex_model,
)
from .contracts import LOCAL_TOOL_PROTOCOL_VERSION, ImageGenerationError
from .local_tool import detect_local_tool
from .proxy import (
    LocalProxyConfigurationError,
    LocalProxyResolution,
    detect_system_proxy,
    resolve_local_proxy,
)

DEFAULT_IMAGE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_REMOTE_MODEL_ALIAS = "qwen_image_2_pro"
IMAGE_REMOTE_PROVIDER = "dashscope"
IMAGE_ADAPTER_ID = "dashscope-qwen-image"
IMAGE_ADAPTER_VERSION = "1.0.0"

CredentialProbe = Callable[[str, str], Awaitable[CredentialValidationResult]]
CodexDiscovery = Callable[[], Awaitable[LocalCodexDiscoveryResponse]]
CodexNetworkProbe = Callable[[str | None, int], Awaitable[CodexNetworkProbeResult]]


class ImageGenerationSettingsServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> ImageGenerationSettingsServiceError:
    return ImageGenerationSettingsServiceError(status_code, code, message)


def mask_api_key(api_key: str) -> str | None:
    stripped = api_key.strip()
    if not stripped:
        return None
    suffix = stripped[-4:] if len(stripped) >= 4 else stripped
    return f"••••••••{suffix}"


def normalize_image_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise _fail(422, "image_endpoint_invalid", "图片模型服务地址格式无效") from exc
    hostname = (parts.hostname or "").lower()
    standard_hosts = {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    }
    workspace_host = hostname.endswith(".maas.aliyuncs.com") and len(hostname.split(".")) >= 5
    if (
        parts.scheme.lower() != "https"
        or (hostname not in standard_hosts and not workspace_host)
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or parts.query
        or parts.fragment
        or parts.path.rstrip("/") != "/api/v1"
    ):
        raise _fail(
            422,
            "image_endpoint_not_allowed",
            "为保护 API Key，图片服务地址仅允许百炼官方 HTTPS /api/v1 接口",
        )
    return urlunsplit(("https", hostname, "/api/v1", "", ""))


def _compatible_base_url(image_base_url: str) -> str:
    parts = urlsplit(image_base_url)
    return urlunsplit(("https", parts.netloc, "/compatible-mode/v1", "", ""))


async def _default_credential_probe(
    api_key: str,
    image_base_url: str,
) -> CredentialValidationResult:
    provider = DashScopeProvider(
        api_key=api_key,
        base_url=_compatible_base_url(image_base_url),
        timeout_seconds=30,
    )
    return await provider.validate_credentials("qwen-plus")


def _parse_time(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_config_value(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _parse_fixed_args() -> list[str]:
    raw = get_config_value("VIRAL_DNA_IMAGE_LOCAL_FIXED_ARGS", "[]")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if isinstance(item, str)][:20]


def _replace_fixed_arg(values: list[str], name: str, value: str) -> list[str]:
    updated = list(values)
    try:
        index = updated.index(name)
    except ValueError:
        updated.extend([name, value])
        return updated
    if index + 1 < len(updated):
        updated[index + 1] = value
    else:
        updated.append(value)
    return updated


def _parse_capability() -> ImageGenerationCapability | None:
    raw = get_config_value("VIRAL_DNA_IMAGE_CAPABILITY_SNAPSHOT", "")
    if not raw:
        return None
    try:
        return ImageGenerationCapability.model_validate_json(raw)
    except ValueError:
        return None


def _default_image_base_url() -> str:
    configured = get_config_value("DASHSCOPE_BASE_URL", "").strip()
    if configured:
        parts = urlsplit(configured)
        candidate = urlunsplit(("https", parts.netloc, "/api/v1", "", ""))
        try:
            return normalize_image_base_url(candidate)
        except ImageGenerationSettingsServiceError:
            pass
    return DEFAULT_IMAGE_BASE_URL


def _resolve_proxy_or_fail(
    mode: str,
    manual_url: str | None,
) -> LocalProxyResolution:
    try:
        return resolve_local_proxy(mode, manual_url)
    except LocalProxyConfigurationError as exc:
        raise _fail(422, "local_proxy_invalid", str(exc)) from exc


class ImageGenerationSettingsService:
    def __init__(
        self,
        credential_probe: CredentialProbe | None = None,
        codex_discovery: CodexDiscovery | None = None,
        codex_network_probe: CodexNetworkProbe | None = None,
    ) -> None:
        self._credential_probe = credential_probe or _default_credential_probe
        self._codex_discovery = codex_discovery or discover_codex_environment
        self._codex_network_probe = codex_network_probe or probe_codex_network

    def get(
        self,
        *,
        validation_latency_ms: int | None = None,
    ) -> ImageGenerationSettingsResponse:
        try:
            catalog = load_image_model_catalog()
        except ImageModelCatalogError as exc:
            raise _fail(503, "image_catalog_unavailable", str(exc)) from exc
        alias = (
            get_config_value(
                "VIRAL_DNA_IMAGE_REMOTE_MODEL_ALIAS",
                DEFAULT_REMOTE_MODEL_ALIAS,
            ).strip()
            or DEFAULT_REMOTE_MODEL_ALIAS
        )
        try:
            selected = catalog.option(alias)
        except ImageModelCatalogError:
            alias = DEFAULT_REMOTE_MODEL_ALIAS
            selected = catalog.option(alias)
        raw_mode = get_config_value(
            "VIRAL_DNA_IMAGE_EXECUTION_MODE",
            ImageExecutionMode.REMOTE_API.value,
        )
        try:
            mode = ImageExecutionMode(raw_mode)
        except ValueError:
            mode = ImageExecutionMode.REMOTE_API
        if mode not in {
            ImageExecutionMode.REMOTE_API,
            ImageExecutionMode.LOCAL_TOOL,
        }:
            mode = ImageExecutionMode.REMOTE_API
        raw_cost_source = get_config_value(
            "VIRAL_DNA_IMAGE_LOCAL_COST_SOURCE",
            GenerationCostSource.UNKNOWN.value,
        )
        try:
            local_cost_source = GenerationCostSource(raw_cost_source)
        except ValueError:
            local_cost_source = GenerationCostSource.UNKNOWN
        if local_cost_source == GenerationCostSource.PROVIDER_REPORTED:
            local_cost_source = GenerationCostSource.UNKNOWN
        local_model_policy = get_config_value(
            "VIRAL_DNA_IMAGE_LOCAL_MODEL_POLICY",
            "latest_flagship",
        )
        if local_model_policy not in {"latest_flagship", "pinned", "balanced"}:
            local_model_policy = "latest_flagship"
        local_reasoning_effort = get_config_value(
            "VIRAL_DNA_IMAGE_LOCAL_REASONING_EFFORT",
            "xhigh",
        )
        if local_reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            local_reasoning_effort = "xhigh"
        local_proxy_mode = get_config_value(
            "VIRAL_DNA_IMAGE_LOCAL_PROXY_MODE",
            "system",
        )
        if local_proxy_mode not in {"system", "manual", "disabled"}:
            local_proxy_mode = "system"
        local_proxy_url = (
            get_config_value("VIRAL_DNA_IMAGE_LOCAL_PROXY_URL", "").strip() or None
        )
        detected_proxy = detect_system_proxy()
        try:
            effective_proxy = resolve_local_proxy(local_proxy_mode, local_proxy_url)
        except LocalProxyConfigurationError:
            local_proxy_mode = "system"
            local_proxy_url = None
            effective_proxy = detected_proxy
        raw_unit_cost = get_config_value("VIRAL_DNA_IMAGE_LOCAL_UNIT_COST_MICROS", "")
        try:
            local_unit_cost = int(raw_unit_cost) if raw_unit_cost else None
        except ValueError:
            local_unit_cost = None
        remote_base = get_config_value(
            "DASHSCOPE_IMAGE_BASE_URL",
            _default_image_base_url(),
        )
        try:
            remote_base = normalize_image_base_url(remote_base)
        except ImageGenerationSettingsServiceError:
            remote_base = _default_image_base_url()
        api_key = get_config_value("DASHSCOPE_API_KEY", "")
        capability = _parse_capability()
        if capability is None and mode == ImageExecutionMode.REMOTE_API:
            capability = selected.capabilities
        return ImageGenerationSettingsResponse(
            enabled=get_config_value("VIRAL_DNA_IMAGE_GENERATION_ENABLED", "false").lower()
            == "true",
            execution_mode=mode,
            default_candidate_count=_parse_int(
                "VIRAL_DNA_IMAGE_DEFAULT_CANDIDATES",
                1,
                1,
                4,
            ),
            remote_provider=IMAGE_REMOTE_PROVIDER,
            remote_model_alias=alias,
            remote_model=selected.model,
            remote_base_url=remote_base,
            api_key_configured=bool(api_key.strip()),
            api_key_hint=mask_api_key(api_key),
            local_adapter_id=get_config_value(
                "VIRAL_DNA_IMAGE_LOCAL_ADAPTER_ID",
                "viral_dna_json_v1",
            ),
            local_executable_path=(
                get_config_value("VIRAL_DNA_IMAGE_LOCAL_EXECUTABLE", "").strip() or None
            ),
            local_fixed_args=_parse_fixed_args(),
            local_timeout_seconds=_parse_int(
                "VIRAL_DNA_IMAGE_LOCAL_TIMEOUT_SECONDS",
                300,
                10,
                3600,
            ),
            local_concurrency=_parse_int(
                "VIRAL_DNA_IMAGE_LOCAL_CONCURRENCY",
                1,
                1,
                8,
            ),
            local_protocol_version=get_config_value(
                "VIRAL_DNA_IMAGE_LOCAL_PROTOCOL_VERSION",
                LOCAL_TOOL_PROTOCOL_VERSION,
            ),
            local_tool_id=(get_config_value("VIRAL_DNA_IMAGE_LOCAL_TOOL_ID", "").strip() or None),
            local_tool_version=(
                get_config_value("VIRAL_DNA_IMAGE_LOCAL_TOOL_VERSION", "").strip() or None
            ),
            local_cost_source=local_cost_source,
            local_unit_cost_micros=local_unit_cost,
            local_model_policy=local_model_policy,
            local_model=(
                get_config_value("VIRAL_DNA_IMAGE_LOCAL_MODEL", "").strip() or None
            ),
            local_reasoning_effort=local_reasoning_effort,
            local_proxy_mode=local_proxy_mode,
            local_proxy_url=local_proxy_url,
            local_proxy_detected_url=detected_proxy.url,
            local_proxy_effective_url=effective_proxy.url,
            local_proxy_source=effective_proxy.source,
            last_validated_at=_parse_time(
                get_config_value("VIRAL_DNA_IMAGE_LAST_VALIDATED_AT", "")
            ),
            validation_latency_ms=validation_latency_ms,
            catalog_version=catalog.catalog_version,
            pricing_version=catalog.pricing_version,
            selected_capabilities=capability,
            models=catalog.options(IMAGE_REMOTE_PROVIDER),
        )

    async def update(
        self,
        payload: ImageGenerationSettingsUpdate,
    ) -> ImageGenerationSettingsResponse:
        try:
            catalog = load_image_model_catalog()
            selected = catalog.option(payload.remote_model_alias)
        except ImageModelCatalogError as exc:
            raise _fail(422, "image_model_invalid", "所选图片模型不在当前能力目录中") from exc
        if (
            selected.provider != IMAGE_REMOTE_PROVIDER
            or payload.remote_provider != IMAGE_REMOTE_PROVIDER
        ):
            raise _fail(422, "image_provider_invalid", "当前版本仅支持阿里云百炼图片模型")

        local_fixed_args = list(payload.local_fixed_args)
        local_model = payload.local_model
        proxy_resolution = _resolve_proxy_or_fail(
            payload.local_proxy_mode,
            payload.local_proxy_url,
        )
        if payload.local_adapter_id == CODEX_IMAGEGEN_ADAPTER_ID:
            try:
                local_model = resolve_codex_model(
                    payload.local_model_policy,
                    payload.local_model,
                )
            except ValueError as exc:
                raise _fail(422, "codex_model_required", str(exc)) from exc
            local_fixed_args = _replace_fixed_arg(
                local_fixed_args,
                "--model",
                local_model,
            )
            local_fixed_args = _replace_fixed_arg(
                local_fixed_args,
                "--model-policy",
                payload.local_model_policy,
            )
            local_fixed_args = _replace_fixed_arg(
                local_fixed_args,
                "--reasoning-effort",
                payload.local_reasoning_effort,
            )
            if len(local_fixed_args) > 20:
                raise _fail(
                    422,
                    "codex_fixed_args_too_many",
                    "Codex 本机工具固定参数不能超过 20 项",
                )

        validated_at = datetime.now(UTC).isoformat()
        capability: ImageGenerationCapability
        latency_ms: int
        updates: dict[str, str] = {
            "VIRAL_DNA_IMAGE_GENERATION_ENABLED": "true",
            "VIRAL_DNA_IMAGE_EXECUTION_MODE": payload.execution_mode,
            "VIRAL_DNA_IMAGE_DEFAULT_CANDIDATES": str(payload.default_candidate_count),
            "VIRAL_DNA_IMAGE_REMOTE_PROVIDER": IMAGE_REMOTE_PROVIDER,
            "VIRAL_DNA_IMAGE_REMOTE_MODEL_ALIAS": payload.remote_model_alias,
            "VIRAL_DNA_IMAGE_LOCAL_ADAPTER_ID": payload.local_adapter_id,
            "VIRAL_DNA_IMAGE_LOCAL_EXECUTABLE": payload.local_executable_path or "",
            "VIRAL_DNA_IMAGE_LOCAL_FIXED_ARGS": json.dumps(
                local_fixed_args,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "VIRAL_DNA_IMAGE_LOCAL_TIMEOUT_SECONDS": str(payload.local_timeout_seconds),
            "VIRAL_DNA_IMAGE_LOCAL_CONCURRENCY": str(payload.local_concurrency),
            "VIRAL_DNA_IMAGE_LOCAL_PROTOCOL_VERSION": payload.local_protocol_version,
            "VIRAL_DNA_IMAGE_LOCAL_COST_SOURCE": payload.local_cost_source,
            "VIRAL_DNA_IMAGE_LOCAL_UNIT_COST_MICROS": (
                str(payload.local_unit_cost_micros)
                if payload.local_unit_cost_micros is not None
                else ""
            ),
            "VIRAL_DNA_IMAGE_LOCAL_MODEL_POLICY": payload.local_model_policy,
            "VIRAL_DNA_IMAGE_LOCAL_MODEL": local_model or "",
            "VIRAL_DNA_IMAGE_LOCAL_REASONING_EFFORT": payload.local_reasoning_effort,
            "VIRAL_DNA_IMAGE_LOCAL_PROXY_MODE": payload.local_proxy_mode,
            "VIRAL_DNA_IMAGE_LOCAL_PROXY_URL": (
                proxy_resolution.url if payload.local_proxy_mode == "manual" else ""
            ),
            "VIRAL_DNA_IMAGE_LAST_VALIDATED_AT": validated_at,
        }
        if payload.execution_mode == ImageExecutionMode.REMOTE_API:
            base_url = normalize_image_base_url(payload.remote_base_url or "")
            supplied_key = (
                payload.remote_api_key.get_secret_value().strip() if payload.remote_api_key else ""
            )
            api_key = supplied_key or get_config_value("DASHSCOPE_API_KEY", "").strip()
            if not api_key:
                raise _fail(422, "image_api_key_required", "请填写阿里云百炼 API Key")
            try:
                validation = await self._credential_probe(api_key, base_url)
            except Exception as exc:
                status_code = int(getattr(exc, "status_code", 0) or 0)
                if status_code in {401, 403}:
                    raise _fail(
                        422,
                        "image_api_key_invalid",
                        "API Key 无效，或没有访问当前百炼区域的权限",
                    ) from exc
                if status_code == 429:
                    raise _fail(
                        429,
                        "image_api_rate_limited",
                        "百炼额度不足或请求过于频繁",
                    ) from exc
                raise _fail(
                    503,
                    "image_api_validation_failed",
                    "暂时无法校验百炼 API Key，请检查区域、服务地址和网络",
                ) from exc
            capability = selected.capabilities
            latency_ms = validation.latency_ms
            updates.update(
                {
                    "DASHSCOPE_API_KEY": api_key,
                    "DASHSCOPE_IMAGE_BASE_URL": base_url,
                    "VIRAL_DNA_IMAGE_LOCAL_TOOL_ID": get_config_value(
                        "VIRAL_DNA_IMAGE_LOCAL_TOOL_ID",
                        "",
                    ),
                    "VIRAL_DNA_IMAGE_LOCAL_TOOL_VERSION": get_config_value(
                        "VIRAL_DNA_IMAGE_LOCAL_TOOL_VERSION",
                        "",
                    ),
                }
            )
        else:
            try:
                detection = await detect_local_tool(
                    payload.local_executable_path or "",
                    local_fixed_args,
                    timeout_seconds=min(120, payload.local_timeout_seconds),
                    expected_protocol=payload.local_protocol_version,
                    proxy_url=proxy_resolution.url,
                )
            except ImageGenerationError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            if not detection.capability.image_to_image:
                raise _fail(
                    422,
                    "local_tool_image_edit_required",
                    "本机工具必须支持 image_to_image 能力",
                )
            capability = detection.capability
            latency_ms = detection.latency_ms
            updates.update(
                {
                    "DASHSCOPE_IMAGE_BASE_URL": normalize_image_base_url(
                        payload.remote_base_url or _default_image_base_url()
                    ),
                    "VIRAL_DNA_IMAGE_LOCAL_TOOL_ID": detection.tool_id,
                    "VIRAL_DNA_IMAGE_LOCAL_TOOL_VERSION": detection.tool_version,
                }
            )
        updates["VIRAL_DNA_IMAGE_CAPABILITY_SNAPSHOT"] = capability.model_dump_json()
        try:
            persist_config_values(updates)
        except RuntimeConfigError as exc:
            raise _fail(
                500,
                "image_settings_save_failed",
                "配置已校验，但无法保存到本机配置文件",
            ) from exc
        return self.get(validation_latency_ms=latency_ms)

    async def detect_local(
        self,
        payload: LocalImageToolDetectRequest,
    ) -> LocalImageToolDetectResponse:
        proxy_resolution = _resolve_proxy_or_fail(
            payload.proxy_mode,
            payload.proxy_url,
        )
        try:
            result = await detect_local_tool(
                payload.executable_path,
                payload.fixed_args,
                timeout_seconds=payload.timeout_seconds,
                expected_protocol=payload.protocol_version,
                proxy_url=proxy_resolution.url,
            )
        except ImageGenerationError as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc
        return LocalImageToolDetectResponse(
            tool_id=result.tool_id,
            tool_version=result.tool_version,
            protocol_version=result.protocol_version,
            capabilities=result.capability,
            latency_ms=result.latency_ms,
        )

    async def discover_codex(self) -> LocalCodexDiscoveryResponse:
        return await self._codex_discovery()

    async def test_codex_network(
        self,
        payload: LocalCodexNetworkTestRequest,
    ) -> LocalCodexNetworkTestResponse:
        proxy_resolution = _resolve_proxy_or_fail(
            payload.proxy_mode,
            payload.proxy_url,
        )
        discovery, probe = await asyncio.gather(
            self.discover_codex(),
            self._codex_network_probe(
                proxy_resolution.url,
                payload.timeout_seconds,
            ),
        )
        if probe.reachable and discovery.auth_status == "authenticated":
            message = "ChatGPT 网络可达，Codex 已登录，可以执行本机 ImageGen。"
        elif probe.reachable:
            message = "ChatGPT 网络可达，但 Codex 登录状态异常，请先完成登录。"
        else:
            message = probe.message
        return LocalCodexNetworkTestResponse(
            reachable=probe.reachable,
            auth_status=discovery.auth_status,
            http_status=probe.http_status,
            proxy_source=proxy_resolution.source,
            effective_proxy_url=proxy_resolution.url,
            latency_ms=probe.latency_ms,
            message=message,
        )

    async def auto_configure_codex(
        self,
        payload: LocalCodexAutoConfigureRequest,
    ) -> ImageGenerationSettingsResponse:
        discovery = await self.discover_codex()
        if not discovery.can_auto_configure:
            reason = "；".join(discovery.warnings) or "本机 Codex + ImageGen 环境不完整"
            raise _fail(409, "codex_auto_config_unavailable", reason)
        if not discovery.codex_executable_path:
            raise _fail(409, "codex_cli_not_found", "未找到可直接执行的 Codex CLI")
        try:
            model = resolve_codex_model(payload.model_policy, payload.model)
        except ValueError as exc:
            raise _fail(422, "codex_model_required", str(exc)) from exc

        current = self.get()
        wrapper = discovery.wrapper_path
        fixed_args = [
            wrapper,
            "--codex-executable",
            discovery.codex_executable_path,
            "--model",
            model,
            "--model-policy",
            payload.model_policy,
            "--reasoning-effort",
            payload.reasoning_effort,
            "--codex-timeout",
            "1200",
        ]
        return await self.update(
            ImageGenerationSettingsUpdate(
                execution_mode=ImageExecutionMode.LOCAL_TOOL.value,
                default_candidate_count=payload.default_candidate_count,
                remote_provider=current.remote_provider,
                remote_model_alias=current.remote_model_alias,
                remote_base_url=current.remote_base_url,
                local_adapter_id=CODEX_IMAGEGEN_ADAPTER_ID,
                local_executable_path=sys.executable,
                local_fixed_args=fixed_args,
                local_timeout_seconds=1200,
                local_concurrency=1,
                local_protocol_version=LOCAL_TOOL_PROTOCOL_VERSION,
                local_cost_source=GenerationCostSource.SUBSCRIPTION_QUOTA.value,
                local_unit_cost_micros=None,
                local_model_policy=payload.model_policy,
                local_model=model,
                local_reasoning_effort=payload.reasoning_effort,
                local_proxy_mode=payload.proxy_mode,
                local_proxy_url=payload.proxy_url,
            )
        )
