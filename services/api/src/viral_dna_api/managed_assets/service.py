from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from ..models import (
    ManagedAssetKind,
    ManagedAssetMediaType,
    ProviderManagedAssetBinding,
)
from ..runtime_config import get_config_value
from .models import (
    ManagedAssetCatalogResponse,
    ManagedAssetCatalogStatusResponse,
    ManagedAssetGroupSummary,
    ManagedAssetSummary,
)
from .volc_ark import (
    VolcArkAssetApiError,
    VolcArkAssetClient,
    VolcArkAssetCredentials,
)

ACCESS_KEY_ENV = "VIRAL_DNA_VOLC_ARK_ASSET_ACCESS_KEY"
SECRET_KEY_ENV = "VIRAL_DNA_VOLC_ARK_ASSET_SECRET_KEY"
REGION_ENV = "VIRAL_DNA_VOLC_ARK_ASSET_REGION"
PROJECT_ENV = "VIRAL_DNA_VOLC_ARK_ASSET_PROJECT_NAME"
VALIDATED_ENV = "VIRAL_DNA_VOLC_ARK_ASSET_VALIDATED_AT"
ALLOWED_REGIONS = {"cn-beijing", "cn-shanghai"}


class ManagedAssetServiceError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        provider_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.provider_code = provider_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ManagedAssetSettingsState:
    access_key: str
    secret_key: str
    region: str
    project_name: str
    validated_at: str

    @property
    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key)


def _mask(value: str) -> str | None:
    if not value:
        return None
    suffix = value[-4:] if len(value) >= 4 else value
    return f"••••••••{suffix}"


def _as_time(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _kind_to_group_type(kind: ManagedAssetKind) -> str:
    return "AIGC" if kind == ManagedAssetKind.VIRTUAL_PERSON else "LivenessFace"


def _group_type_to_kind(value: object) -> ManagedAssetKind:
    normalized = str(value or "").strip().lower()
    return (
        ManagedAssetKind.VERIFIED_PERSON
        if normalized in {"livenessface", ManagedAssetKind.VERIFIED_PERSON.value}
        else ManagedAssetKind.VIRTUAL_PERSON
    )


def _media_type(value: object) -> ManagedAssetMediaType:
    normalized = str(value or "image").strip().lower()
    try:
        return ManagedAssetMediaType(normalized)
    except ValueError:
        return ManagedAssetMediaType.IMAGE


def _status(value: object) -> str:
    normalized = str(value or "Active").strip().lower()
    return normalized if normalized in {"active", "processing", "failed"} else "failed"


def _service_error(exc: VolcArkAssetApiError) -> ManagedAssetServiceError:
    return ManagedAssetServiceError(
        exc.status_code,
        exc.code,
        str(exc),
        provider_code=exc.provider_code,
        retryable=exc.retryable,
    )


class ManagedAssetCatalogService:
    def settings(self) -> ManagedAssetSettingsState:
        region = get_config_value(REGION_ENV, "cn-beijing").strip() or "cn-beijing"
        if region not in ALLOWED_REGIONS:
            region = "cn-beijing"
        return ManagedAssetSettingsState(
            access_key=(
                get_config_value(ACCESS_KEY_ENV, "").strip()
                or get_config_value("VOLCENGINE_ACCESS_KEY", "").strip()
            ),
            secret_key=(
                get_config_value(SECRET_KEY_ENV, "").strip()
                or get_config_value("VOLCENGINE_SECRET_KEY", "").strip()
            ),
            region=region,
            project_name=get_config_value(PROJECT_ENV, "default").strip() or "default",
            validated_at=get_config_value(VALIDATED_ENV, "").strip(),
        )

    def status(self) -> ManagedAssetCatalogStatusResponse:
        state = self.settings()
        return ManagedAssetCatalogStatusResponse(
            credentials_configured=state.configured,
            access_key_hint=_mask(state.access_key),
            region=state.region,
            project_name=state.project_name,
            validation_status=(
                "valid" if state.configured and state.validated_at else
                "unknown" if state.configured else
                "not_configured"
            ),
            validation_message=(
                "资产目录凭证已校验" if state.configured and state.validated_at else
                "资产目录凭证尚未校验" if state.configured else
                "请在模型与设置中配置火山方舟资产目录 AK/SK"
            ),
        )

    @staticmethod
    def proposed_settings(
        *,
        access_key: str,
        secret_key: str,
        region: str,
        project_name: str,
    ) -> ManagedAssetSettingsState:
        if region not in ALLOWED_REGIONS:
            raise ManagedAssetServiceError(
                422,
                "managed_asset_region_invalid",
                "资产目录区域仅支持华北（北京）或华东（上海）",
            )
        return ManagedAssetSettingsState(
            access_key=access_key.strip(),
            secret_key=secret_key.strip(),
            region=region,
            project_name=project_name.strip() or "default",
            validated_at="",
        )

    @staticmethod
    def _credentials(state: ManagedAssetSettingsState) -> VolcArkAssetCredentials:
        if not state.configured:
            raise ManagedAssetServiceError(
                409,
                "managed_asset_credentials_required",
                "请先在模型与设置中配置火山方舟资产目录 AK/SK",
            )
        return VolcArkAssetCredentials(
            access_key=state.access_key,
            secret_key=state.secret_key,
            region=state.region,
            project_name=state.project_name,
        )

    async def validate_credentials(self, state: ManagedAssetSettingsState) -> None:
        credentials = self._credentials(state)
        try:
            async with VolcArkAssetClient(credentials) as client:
                await client.list_groups(group_type="AIGC", page=1, page_size=1)
        except VolcArkAssetApiError as exc:
            raise _service_error(exc) from exc

    async def catalog(
        self,
        *,
        kind: ManagedAssetKind,
        page: int,
        page_size: int,
        group_id: str | None = None,
        query: str | None = None,
    ) -> ManagedAssetCatalogResponse:
        state = self.settings()
        credentials = self._credentials(state)
        group_type = _kind_to_group_type(kind)
        try:
            async with VolcArkAssetClient(credentials) as client:
                groups_payload, assets_payload = await asyncio.gather(
                    client.list_groups(group_type=group_type, page=1, page_size=100),
                    client.list_assets(
                        group_type=group_type,
                        page=page,
                        page_size=page_size,
                        group_id=group_id,
                        name=query,
                    ),
                )
        except VolcArkAssetApiError as exc:
            raise _service_error(exc) from exc
        groups = [
            self._group_summary(item, fallback_kind=kind, fallback_project=state.project_name)
            for item in groups_payload.get("Items", [])
            if isinstance(item, dict)
        ]
        group_names = {item.id: item.name for item in groups}
        assets = [
            self._asset_summary(
                item,
                fallback_kind=kind,
                fallback_project=state.project_name,
                group_names=group_names,
            )
            for item in assets_payload.get("Items", [])
            if isinstance(item, dict)
        ]
        return ManagedAssetCatalogResponse(
            kind=kind,
            project_name=state.project_name,
            region=state.region,
            groups=groups,
            assets=assets,
            page=int(assets_payload.get("PageNumber") or page),
            page_size=int(assets_payload.get("PageSize") or page_size),
            total=int(assets_payload.get("TotalCount") or len(assets)),
        )

    async def verify_binding(
        self,
        binding: ProviderManagedAssetBinding,
    ) -> ProviderManagedAssetBinding:
        if binding.provider != "volc_ark":
            raise ManagedAssetServiceError(
                422,
                "managed_asset_provider_unsupported",
                "当前仅支持火山方舟托管资产目录",
            )
        state = self.settings()
        credentials = self._credentials(state)
        try:
            async with VolcArkAssetClient(credentials) as client:
                asset_payload = await client.get_asset(binding.asset_id)
                group_id = str(asset_payload.get("GroupId") or binding.group_id or "").strip()
                group_payload = await client.get_group(group_id) if group_id else {}
        except VolcArkAssetApiError as exc:
            raise _service_error(exc) from exc
        status = _status(asset_payload.get("Status"))
        if status != "active":
            raise ManagedAssetServiceError(
                409,
                "managed_asset_not_active",
                "所选托管资产尚未完成处理，当前不能用于视频生成",
            )
        project_name = str(asset_payload.get("ProjectName") or state.project_name).strip()
        if project_name != state.project_name:
            raise ManagedAssetServiceError(
                409,
                "managed_asset_project_mismatch",
                "托管资产与当前方舟 API Key 不属于同一个 ProjectName",
            )
        kind = _group_type_to_kind(group_payload.get("GroupType") or binding.kind.value)
        media_type = _media_type(asset_payload.get("AssetType") or binding.media_type.value)
        if media_type == ManagedAssetMediaType.AUDIO:
            raise ManagedAssetServiceError(
                422,
                "managed_asset_media_unsupported",
                "演员身份当前只支持图片或视频类型的托管资产",
            )
        try:
            return ProviderManagedAssetBinding(
                id=binding.id,
                provider="volc_ark",
                asset_id=binding.asset_id,
                group_id=str(asset_payload.get("GroupId") or binding.group_id or "") or None,
                kind=kind,
                role=binding.role,
                name=str(asset_payload.get("Name") or binding.name or binding.asset_id),
                group_name=str(
                    group_payload.get("Name")
                    or group_payload.get("Title")
                    or binding.group_name
                    or ""
                ) or None,
                media_type=media_type,
                project_name=project_name,
                status="active",
                preview_url=str(asset_payload.get("URL") or binding.preview_url or "") or None,
                bound_at=binding.bound_at,
                last_verified_at=datetime.now(UTC),
            )
        except ValidationError as exc:
            raise ManagedAssetServiceError(
                502,
                "managed_asset_response_invalid",
                "火山方舟返回的资产信息不完整",
            ) from exc

    async def preview_url(self, asset_id: str) -> str:
        state = self.settings()
        credentials = self._credentials(state)
        try:
            async with VolcArkAssetClient(credentials) as client:
                payload = await client.get_asset(asset_id)
        except VolcArkAssetApiError as exc:
            raise _service_error(exc) from exc
        if _status(payload.get("Status")) != "active":
            raise ManagedAssetServiceError(
                409,
                "managed_asset_not_active",
                "所选托管资产尚未完成处理，当前没有可用预览",
            )
        project_name = str(payload.get("ProjectName") or state.project_name).strip()
        if project_name != state.project_name:
            raise ManagedAssetServiceError(
                409,
                "managed_asset_project_mismatch",
                "托管资产与当前目录配置不属于同一个 ProjectName",
            )
        preview_url = str(payload.get("URL") or "").strip()
        parsed = urlsplit(preview_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ManagedAssetServiceError(
                502,
                "managed_asset_preview_unavailable",
                "火山方舟没有返回安全可用的资产预览地址",
            )
        return preview_url

    @staticmethod
    def _group_summary(
        payload: dict[str, Any],
        *,
        fallback_kind: ManagedAssetKind,
        fallback_project: str,
    ) -> ManagedAssetGroupSummary:
        name = str(payload.get("Name") or payload.get("Title") or payload.get("Id") or "未命名")
        return ManagedAssetGroupSummary(
            id=str(payload.get("Id") or payload.get("GroupId") or name),
            name=name,
            title=str(payload.get("Title") or "") or None,
            description=str(payload.get("Description") or ""),
            kind=_group_type_to_kind(payload.get("GroupType") or fallback_kind.value),
            project_name=str(payload.get("ProjectName") or fallback_project),
            created_at=_as_time(payload.get("CreateTime")),
            updated_at=_as_time(payload.get("UpdateTime")),
        )

    @staticmethod
    def _asset_summary(
        payload: dict[str, Any],
        *,
        fallback_kind: ManagedAssetKind,
        fallback_project: str,
        group_names: dict[str, str],
    ) -> ManagedAssetSummary:
        group_id = str(payload.get("GroupId") or "")
        asset_id = str(payload.get("Id") or "")
        return ManagedAssetSummary(
            id=asset_id,
            group_id=group_id,
            group_name=group_names.get(group_id),
            name=str(payload.get("Name") or asset_id or "未命名"),
            kind=fallback_kind,
            media_type=_media_type(payload.get("AssetType")),
            status=_status(payload.get("Status")),
            preview_url=str(payload.get("URL") or "") or None,
            project_name=str(payload.get("ProjectName") or fallback_project),
            created_at=_as_time(payload.get("CreateTime")),
            updated_at=_as_time(payload.get("UpdateTime")),
            last_inference_at=_as_time(payload.get("LastInferenceTime")),
        )
