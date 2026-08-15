from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .signing import canonical_json, sign_volcengine_request


@dataclass(frozen=True, slots=True)
class VolcArkAssetCredentials:
    access_key: str
    secret_key: str
    region: str
    project_name: str


class VolcArkAssetApiError(RuntimeError):
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


def _provider_error(payload: dict[str, Any]) -> tuple[str, str]:
    metadata = payload.get("ResponseMetadata")
    if not isinstance(metadata, dict):
        return "", ""
    error = metadata.get("Error")
    if not isinstance(error, dict):
        return "", ""
    return str(error.get("Code") or ""), str(error.get("Message") or "")


def _mapped_error(status_code: int, payload: dict[str, Any]) -> VolcArkAssetApiError:
    provider_code, provider_message = _provider_error(payload)
    lowered = f"{provider_code} {provider_message}".lower()
    if status_code in {401, 403} or any(
        token in lowered
        for token in ("signature", "accessdenied", "invalidaccesskey", "unauthorized")
    ):
        return VolcArkAssetApiError(
            401 if "signature" in lowered or "accesskey" in lowered else 403,
            "managed_asset_auth_invalid"
            if "signature" in lowered or "accesskey" in lowered
            else "managed_asset_permission_denied",
            (
                "火山方舟资产目录 AK/SK 无效或签名校验失败"
                if "signature" in lowered or "accesskey" in lowered
                else "当前火山账号没有素材库权限，请检查 IAM 的 ark:*Asset* 权限和高级创作权益"
            ),
            provider_code=provider_code or None,
        )
    if status_code == 429 or "throttl" in lowered or "ratelimit" in lowered:
        return VolcArkAssetApiError(
            429,
            "managed_asset_rate_limited",
            "火山方舟资产目录请求过于频繁，请稍后重试",
            provider_code=provider_code or None,
            retryable=True,
        )
    return VolcArkAssetApiError(
        502 if status_code < 500 else 503,
        "managed_asset_provider_failed",
        provider_message or "火山方舟资产目录返回了无法识别的错误",
        provider_code=provider_code or None,
        retryable=status_code >= 500,
    )


class VolcArkAssetClient:
    service = "ark"
    version = "2024-01-01"

    def __init__(
        self,
        credentials: VolcArkAssetCredentials,
        *,
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        self.host = f"ark.{credentials.region}.volcengineapi.com"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=15),
            transport=transport,
        )
    async def __aenter__(self) -> VolcArkAssetClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = canonical_json(payload)
        url, headers = sign_volcengine_request(
            access_key=self.credentials.access_key,
            secret_key=self.credentials.secret_key,
            region=self.credentials.region,
            service=self.service,
            host=self.host,
            action=action,
            version=self.version,
            body=body,
        )
        try:
            response = await self._client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise VolcArkAssetApiError(
                503,
                "managed_asset_provider_unavailable",
                "无法连接火山方舟资产目录服务",
                retryable=True,
            ) from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise VolcArkAssetApiError(
                502,
                "managed_asset_response_invalid",
                "火山方舟资产目录返回了无效 JSON",
            ) from exc
        payload_dict = result if isinstance(result, dict) else {}
        provider_code, _ = _provider_error(payload_dict)
        if response.is_error or provider_code:
            raise _mapped_error(response.status_code, payload_dict)
        provider_result = payload_dict.get("Result")
        return provider_result if isinstance(provider_result, dict) else payload_dict

    async def list_groups(
        self,
        *,
        group_type: str,
        page: int = 1,
        page_size: int = 100,
        name: str | None = None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {"GroupType": group_type}
        if name:
            filters["Name"] = name
        return await self.call(
            "ListAssetGroups",
            {
                "Filter": filters,
                "PageNumber": page,
                "PageSize": page_size,
                "SortBy": "UpdateTime",
                "SortOrder": "Desc",
                "ProjectName": self.credentials.project_name,
            },
        )

    async def list_assets(
        self,
        *,
        group_type: str,
        page: int,
        page_size: int,
        group_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {
            "GroupType": group_type,
            "Statuses": ["Active"],
        }
        if group_id:
            filters["GroupIds"] = [group_id]
        if name:
            filters["Name"] = name
        return await self.call(
            "ListAssets",
            {
                "Filter": filters,
                "PageNumber": page,
                "PageSize": page_size,
                "SortBy": "UpdateTime",
                "SortOrder": "Desc",
                "ProjectName": self.credentials.project_name,
            },
        )

    async def get_asset(self, asset_id: str) -> dict[str, Any]:
        return await self.call(
            "GetAsset",
            {"Id": asset_id, "ProjectName": self.credentials.project_name},
        )

    async def get_group(self, group_id: str) -> dict[str, Any]:
        return await self.call(
            "GetAssetGroup",
            {"Id": group_id, "ProjectName": self.credentials.project_name},
        )
