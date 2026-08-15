from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from viral_dna_api.managed_assets import service as managed_asset_service_module
from viral_dna_api.managed_assets.service import ManagedAssetCatalogService
from viral_dna_api.managed_assets.signing import canonical_json, sign_volcengine_request
from viral_dna_api.managed_assets.volc_ark import (
    VolcArkAssetClient,
    VolcArkAssetCredentials,
)
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.contracts import (
    OrderedReferenceFrame,
    OrderedReferenceVideo,
    ProviderManagedAssetReference,
    ProviderVideoRequest,
)
from viral_dna_api.video_generation.providers.seedance.request_mapper import (
    build_seedance_request,
)
from viral_dna_api.video_references.domain import PersonReferencePolicy


def _frame(path: Path, ordinal: int) -> OrderedReferenceFrame:
    path.write_bytes(f"frame-{ordinal}".encode())
    return OrderedReferenceFrame(
        visual_beat_id=uuid4(),
        ordinal=ordinal,
        title=f"画面 {ordinal}",
        candidate_id=uuid4(),
        path=path,
        relative_path=path.name,
        sha256=f"{ordinal:x}" * 64,
        start_ratio=(ordinal - 1) / 2,
        end_ratio=ordinal / 2,
        transition_to_next_type="cut",
        transition_to_next_duration_seconds=0,
    )


def _managed_reference(*, media_type: str = "image") -> ProviderManagedAssetReference:
    return ProviderManagedAssetReference(
        binding_id=uuid4(),
        provider="volc_ark",
        asset_id="asset-virtual-001",
        group_id="group-001",
        kind="virtual_person",
        role="actor_identity",
        name="小喵酱",
        media_type=media_type,
        project_name="default",
        uri="asset://asset-virtual-001",
    )


def test_seedance_catalog_declares_provider_managed_asset_capability() -> None:
    catalog = load_video_model_catalog()
    for alias in ("seedance_2_0", "seedance_2_0_fast", "seedance_2_0_mini"):
        capability = catalog.option(alias).capability.managed_assets
        assert capability.supported is True
        assert capability.provider == "volc_ark"
        assert capability.catalog_browsing is True
        assert capability.reference_transport == "asset_uri"
        assert capability.maximum_bindings == 1
        assert {item.value for item in capability.asset_kinds} == {
            "virtual_person",
            "verified_person",
        }
        assert [item.value for item in capability.roles] == ["actor_identity"]
        person_capability = catalog.option(alias).capability.person_references
        assert person_capability.policy == PersonReferencePolicy.MANAGED_REQUIRED
        assert person_capability.allow_raw_photoreal_person is False
        assert person_capability.supports_pose_proxy_image is True
        assert person_capability.supports_motion_proxy_video is True

    assert catalog.option("bailian_wan_2_7_r2v").capability.managed_assets.supported is False
    assert catalog.option("minimax_h3").capability.managed_assets.supported is False
    assert (
        catalog.option("bailian_wan_2_7_r2v").capability.person_references.policy
        == PersonReferencePolicy.RAW_SUPPORTED
    )
    assert (
        catalog.option("minimax_h3").capability.person_references.policy
        == PersonReferencePolicy.RAW_SUPPORTED
    )


def test_volc_signing_is_deterministic_and_never_exposes_secret_key() -> None:
    body = canonical_json({"ProjectName": "default", "PageNumber": 1})
    url, headers = sign_volcengine_request(
        access_key="AKIDEXAMPLE",
        secret_key="SECRET-DO-NOT-LEAK",
        region="cn-beijing",
        service="ark",
        host="ark.cn-beijing.volcengineapi.com",
        action="ListAssets",
        version="2024-01-01",
        body=body,
        now=datetime(2026, 8, 14, 1, 2, 3, tzinfo=UTC),
    )

    assert url.endswith("?Action=ListAssets&Version=2024-01-01")
    assert headers["X-Date"] == "20260814T010203Z"
    assert "Credential=AKIDEXAMPLE/20260814/cn-beijing/ark/request" in headers[
        "Authorization"
    ]
    assert "SECRET-DO-NOT-LEAK" not in json.dumps(headers)


def test_volc_catalog_client_uses_project_and_active_asset_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "Result": {
                    "Items": [
                        {
                            "Id": "asset-001",
                            "Name": "虚拟演员 A",
                            "GroupId": "group-001",
                            "Status": "Active",
                        }
                    ],
                    "PageNumber": 1,
                    "PageSize": 24,
                    "TotalCount": 1,
                }
            },
        )

    async def scenario() -> None:
        credentials = VolcArkAssetCredentials(
            access_key="ak",
            secret_key="sk",
            region="cn-beijing",
            project_name="project-a",
        )
        async with VolcArkAssetClient(
            credentials,
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await client.list_assets(
                group_type="AIGC",
                page=1,
                page_size=24,
                group_id="group-001",
                name="演员",
            )
        assert result["TotalCount"] == 1

    asyncio.run(scenario())
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["ProjectName"] == "project-a"
    assert body["Filter"] == {
        "GroupType": "AIGC",
        "Statuses": ["Active"],
        "GroupIds": ["group-001"],
        "Name": "演员",
    }
    assert requests[0].headers["Authorization"].startswith("HMAC-SHA256 Credential=ak/")


def test_managed_asset_preview_refreshes_the_provider_url(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get_asset(self, asset_id: str) -> dict[str, str]:
            assert asset_id == "asset-virtual-001"
            return {
                "Id": asset_id,
                "Status": "Active",
                "ProjectName": "project-a",
                "URL": "https://example.tos-cn-beijing.volces.com/fresh-preview.jpg",
            }

    monkeypatch.setenv("VIRAL_DNA_VOLC_ARK_ASSET_ACCESS_KEY", "ak")
    monkeypatch.setenv("VIRAL_DNA_VOLC_ARK_ASSET_SECRET_KEY", "sk")
    monkeypatch.setenv("VIRAL_DNA_VOLC_ARK_ASSET_PROJECT_NAME", "project-a")
    monkeypatch.setattr(managed_asset_service_module, "VolcArkAssetClient", FakeClient)

    preview_url = asyncio.run(
        ManagedAssetCatalogService().preview_url("asset-virtual-001")
    )

    assert preview_url.endswith("/fresh-preview.jpg")


def test_seedance_places_managed_identity_before_local_frames_and_shifts_labels(
    tmp_path: Path,
) -> None:
    frames = (
        _frame(tmp_path / "first.jpg", 1),
        _frame(tmp_path / "second.jpg", 2),
    )
    payload = build_seedance_request(
        ProviderVideoRequest(
            request_id=uuid4(),
            ordinal=1,
            model_alias="seedance_2_0",
            provider_model="doubao-seedance-2-0-260128",
            prompt="图1走向图2，图号顺序就是画面出现顺序",
            negative_prompt="身份漂移",
            reference_frames=frames,
            managed_asset_references=(_managed_reference(),),
            duration_seconds=5,
            resolution="720P",
            aspect_ratio="9:16",
            width=720,
            height=1280,
        )
    )

    text = payload["content"][0]["text"]
    assert "图片1是本分镜唯一演员身份来源" in text
    assert "图片2走向图片3" in text
    assert "asset-virtual-001" not in text
    assert payload["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "asset://asset-virtual-001"},
        "role": "reference_image",
    }
    assert [item["role"] for item in payload["content"][2:]] == [
        "reference_image",
        "reference_image",
    ]


def test_seedance_maps_provider_managed_video_as_reference_video(tmp_path: Path) -> None:
    payload = build_seedance_request(
        ProviderVideoRequest(
            request_id=uuid4(),
            ordinal=1,
            model_alias="seedance_2_0",
            provider_model="doubao-seedance-2-0-260128",
            prompt="图1保持动作",
            negative_prompt="",
            reference_frames=(_frame(tmp_path / "frame.jpg", 1),),
            managed_asset_references=(_managed_reference(media_type="video"),),
            duration_seconds=5,
            resolution="720P",
            aspect_ratio="9:16",
            width=720,
            height=1280,
        )
    )

    assert "视频1是本分镜唯一演员身份来源" in payload["content"][0]["text"]
    assert payload["content"][1] == {
        "type": "video_url",
        "video_url": {"url": "asset://asset-virtual-001"},
        "role": "reference_video",
    }


def test_seedance_submits_managed_identity_before_identity_free_motion_proxy(
    tmp_path: Path,
) -> None:
    proxy_path = tmp_path / "motion-proxy.mp4"
    proxy_path.write_bytes(b"identity-free-motion-proxy")
    proxy = OrderedReferenceVideo(
        proxy_asset_id=uuid4(),
        visual_beat_id=uuid4(),
        ordinal=1,
        title="无身份动作代理",
        path=proxy_path,
        relative_path=proxy_path.name,
        sha256="e" * 64,
    )
    payload = build_seedance_request(
        ProviderVideoRequest(
            request_id=uuid4(),
            ordinal=1,
            model_alias="seedance_2_0",
            provider_model="doubao-seedance-2-0-260128",
            prompt="演员完成参考动作",
            negative_prompt="",
            reference_frames=(),
            reference_videos=(proxy,),
            managed_asset_references=(_managed_reference(),),
            reference_manifest={"strategy": "managed_identity_with_motion_proxy"},
            duration_seconds=5,
            resolution="720P",
            aspect_ratio="9:16",
            width=720,
            height=1280,
        )
    )

    assert payload["content"][1]["image_url"]["url"] == "asset://asset-virtual-001"
    assert payload["content"][2]["type"] == "video_url"
    assert payload["content"][2]["role"] == "reference_video"
    assert payload["content"][2]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert len(payload["content"]) == 3
    assert "唯一演员身份来源" in payload["content"][0]["text"]
    assert "无身份、无纹理的动作代理" in payload["content"][0]["text"]
