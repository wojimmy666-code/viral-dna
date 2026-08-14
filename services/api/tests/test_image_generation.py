from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from viral_dna_api.ai.providers.dashscope import CredentialValidationResult
from viral_dna_api.image_generation import codex_local
from viral_dna_api.image_generation.catalog import load_image_model_catalog
from viral_dna_api.image_generation.contracts import (
    AdapterIdentity,
    AdapterRequest,
    ImageGenerationRequest,
    ImageReferenceInput,
    build_reference_inputs,
)
from viral_dna_api.image_generation.dashscope import DashScopeQwenImageAdapter
from viral_dna_api.image_generation.gateway import (
    ImageGenerationGateway,
    ImageGenerationGatewayError,
    _compiled_prompt,
    _negative_prompt,
)
from viral_dna_api.image_generation.identity_policy import (
    IdentityPolicyViolation,
    build_input_manifest,
    validate_identity_bindings,
    validate_identity_generation,
)
from viral_dna_api.image_generation.local_tool import (
    CodexSandboxPreflightResult,
    _codex_windows_sandbox_error,
    detect_local_tool,
    validate_fixed_args,
)
from viral_dna_api.image_generation.settings import (
    ImageGenerationSettingsService,
    normalize_image_base_url,
)
from viral_dna_api.models import (
    GenerationCostSource,
    ImageExecutionMode,
    ImageGenerationCapability,
    ImageGenerationInputMode,
    ImageGenerationSettingsUpdate,
    LocalCodexAutoConfigureRequest,
    LocalCodexDiscoveryResponse,
    LocalCodexNetworkTestRequest,
    LocalCodexSandboxTestRequest,
    ModelUsage,
    ProductionProject,
    ReferenceAsset,
    ReferenceAssetType,
    ReferenceBinding,
    ReferenceRole,
    ShotPlan,
)
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager

IMAGE_ENV_KEYS = (
    "VIRAL_DNA_IMAGE_GENERATION_ENABLED",
    "VIRAL_DNA_IMAGE_EXECUTION_MODE",
    "VIRAL_DNA_IMAGE_DEFAULT_CANDIDATES",
    "VIRAL_DNA_IMAGE_REMOTE_PROVIDER",
    "VIRAL_DNA_IMAGE_REMOTE_MODEL_ALIAS",
    "DASHSCOPE_IMAGE_BASE_URL",
    "VIRAL_DNA_IMAGE_LOCAL_ADAPTER_ID",
    "VIRAL_DNA_IMAGE_LOCAL_EXECUTABLE",
    "VIRAL_DNA_IMAGE_LOCAL_FIXED_ARGS",
    "VIRAL_DNA_IMAGE_LOCAL_TIMEOUT_SECONDS",
    "VIRAL_DNA_IMAGE_LOCAL_CONCURRENCY",
    "VIRAL_DNA_IMAGE_LOCAL_PROTOCOL_VERSION",
    "VIRAL_DNA_IMAGE_LOCAL_TOOL_ID",
    "VIRAL_DNA_IMAGE_LOCAL_TOOL_VERSION",
    "VIRAL_DNA_IMAGE_LOCAL_COST_SOURCE",
    "VIRAL_DNA_IMAGE_LOCAL_UNIT_COST_MICROS",
    "VIRAL_DNA_IMAGE_LOCAL_MODEL_POLICY",
    "VIRAL_DNA_IMAGE_LOCAL_MODEL",
    "VIRAL_DNA_IMAGE_LOCAL_REASONING_EFFORT",
    "VIRAL_DNA_IMAGE_LOCAL_PROXY_MODE",
    "VIRAL_DNA_IMAGE_LOCAL_PROXY_URL",
    "VIRAL_DNA_IMAGE_LOCAL_WINDOWS_SANDBOX_MODE",
    "VIRAL_DNA_IMAGE_CAPABILITY_SNAPSHOT",
    "VIRAL_DNA_IMAGE_LAST_VALIDATED_AT",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
)

FAKE_TOOL = """
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    command = sys.argv[1]
    if command == "capabilities":
        print(json.dumps({
            "tool_id": "fake-imagegen",
            "tool_version": "1.2.3",
            "protocol_version": "viral-dna-image-tool/v1",
            "capabilities": {
                "text_to_image": True,
                "image_to_image": True,
                "multi_reference": True,
                "max_reference_images": 4,
                "max_input_images": 5,
                "max_candidates": 4,
                "maximum_width": 2048,
                "maximum_height": 2048,
                "maximum_pixels": 4194304,
                "supported_formats": ["png", "jpeg", "webp"],
                "supports_negative_prompt": True,
                "supports_seed": True,
            },
        }))
        return
    request_path = Path(sys.argv[sys.argv.index("--request") + 1])
    output_root = Path(sys.argv[sys.argv.index("--output") + 1])
    request = json.loads(request_path.read_text("utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    candidates = []
    for ordinal in range(1, request["candidate_count"] + 1):
        path = output_root / f"fake-{ordinal}.png"
        Image.new("RGB", (320, 576), (100 + ordinal, 80, 190)).save(path, "PNG")
        payload = path.read_bytes()
        candidates.append({
            "path": path.name,
            "media_type": "image/png",
            "width": 320,
            "height": 576,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    (output_root / "result.json").write_text(json.dumps({
        "status": "completed",
        "protocol_version": "viral-dna-image-tool/v1",
        "tool_id": "fake-imagegen",
        "tool_version": "1.2.3",
        "candidates": candidates,
        "usage": {
            "image_count": len(candidates),
            "https_proxy": os.getenv("HTTPS_PROXY"),
        },
    }), "utf-8")


if __name__ == "__main__":
    main()
"""

FAKE_CODEX = """
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    if "--version" in sys.argv:
        print("codex-cli 99.0-test")
        return
    if "sandbox" in sys.argv:
        run_root = Path(sys.argv[sys.argv.index("--cd") + 1])
        (run_root / "codex-sandbox-argv.json").write_text(
            json.dumps(sys.argv),
            "utf-8",
        )
        print("viral-dna-codex-sandbox-ok")
        return
    if "exec" not in sys.argv:
        raise SystemExit(2)
    run_root = Path(sys.argv[sys.argv.index("--cd") + 1])
    (run_root / "codex-exec-argv.json").write_text(json.dumps(sys.argv), "utf-8")
    output_root = run_root / "tool-output"
    output_root.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 576), (76, 103, 220)).save(
        output_root / "codex-candidate.png",
        "PNG",
    )
    print('{"type":"turn.completed"}')


if __name__ == "__main__":
    main()
"""


@pytest.fixture(autouse=True)
def restore_image_environment():
    tracked = (*IMAGE_ENV_KEYS, "VIRAL_DNA_ENV_FILE", "VIRAL_DNA_WORKSPACE_ROOT")
    original = {name: os.environ.get(name) for name in tracked}
    yield
    for name, value in original.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def isolate_image_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    for name in IMAGE_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def test_gateway_rejects_generation_when_no_real_engine_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    workspace = WorkspaceManager()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)

    with pytest.raises(ImageGenerationGatewayError) as error:
        asyncio.run(
            ImageGenerationGateway(workspace).generate(
                project,
                _shot(project.id),
                uuid4(),
                [],
                [],
                candidate_count=1,
                source_path=None,
            )
        )

    assert error.value.status_code == 409
    assert error.value.code == "image_generation_not_configured"


def write_image(path: Path, *, size: tuple[int, int] = (720, 1280)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (130, 90, 200)).save(path, "JPEG")
    return path


def write_fake_tool(tmp_path: Path) -> Path:
    path = tmp_path / "fake_image_tool.py"
    path.write_text(FAKE_TOOL, "utf-8")
    return path


def write_fake_codex(tmp_path: Path) -> Path:
    path = tmp_path / "fake_codex.py"
    path.write_text(FAKE_CODEX, "utf-8")
    return path


def is_file(path: Path) -> bool:
    if os.name != "nt":
        return path.is_file()
    separator = chr(92)
    raw = str(path)
    if raw.startswith(separator * 2):
        extended = f"{separator}{separator}?{separator}UNC{separator}{raw[2:]}"
    else:
        extended = f"{separator}{separator}?{separator}{raw}"
    return Path(extended).is_file()


def filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    if raw.startswith(separator * 2):
        return Path(f"{separator}{separator}?{separator}UNC{separator}{raw[2:]}")
    return Path(f"{separator}{separator}?{separator}{raw}")


def test_image_settings_remote_validation_and_secret_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    calls: list[tuple[str, str]] = []

    async def credential_probe(api_key: str, base_url: str) -> CredentialValidationResult:
        calls.append((api_key, base_url))
        return CredentialValidationResult(
            requested_model="qwen-plus",
            resolved_model="qwen-plus",
            provider_request_id="validation-request",
            latency_ms=12,
            usage=ModelUsage(),
        )

    service = ImageGenerationSettingsService(credential_probe)
    before = service.get()
    assert before.enabled is False
    assert before.execution_mode == ImageExecutionMode.REMOTE_API
    assert {item.alias for item in before.models} == {
        "qwen_image_2",
        "qwen_image_2_pro",
    }

    saved = asyncio.run(
        service.update(
            ImageGenerationSettingsUpdate(
                execution_mode="remote_api",
                remote_model_alias="qwen_image_2",
                remote_api_key="test-secret-key",
                remote_base_url="https://dashscope.aliyuncs.com/api/v1",
            )
        )
    )
    assert calls == [
        ("test-secret-key", "https://dashscope.aliyuncs.com/api/v1")
    ]
    assert saved.enabled is True
    assert saved.remote_model == "qwen-image-2.0"
    assert saved.api_key_configured is True
    assert saved.api_key_hint == "••••••••-key"
    assert saved.validation_latency_ms == 12
    assert "test-secret-key" not in saved.model_dump_json()
    assert "DASHSCOPE_API_KEY=test-secret-key" in (tmp_path / ".env.local").read_text(
        "utf-8"
    )


def test_image_endpoint_and_local_arguments_reject_unsafe_values() -> None:
    with pytest.raises(Exception, match="保护 API Key"):
        normalize_image_base_url("https://evil.example/api/v1")
    with pytest.raises(Exception, match="固定参数格式无效"):
        validate_fixed_args(["--profile\nsteal"])


def test_dashscope_adapter_generates_and_downloads_candidates(tmp_path: Path) -> None:
    source = write_image(tmp_path / "source.jpg")
    output_png = tmp_path / "provider.png"
    Image.new("RGB", (720, 1280), (40, 120, 210)).save(output_png, "PNG")
    output_payload = output_png.read_bytes()
    request_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    result_url = "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/result.png"
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == request_url:
            received["authorization"] = request.headers.get("authorization")
            received["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [{"image": result_url}],
                                }
                            }
                        ]
                    },
                    "usage": {"image_count": 1, "width": 720, "height": 1280},
                    "request_id": "provider-request-1",
                },
            )
        if str(request.url) == result_url:
            return httpx.Response(
                200,
                content=output_payload,
                headers={"content-type": "image/png"},
            )
        return httpx.Response(404)

    option = load_image_model_catalog().option("qwen_image_2_pro")
    identity = AdapterIdentity(
        execution_mode=ImageExecutionMode.REMOTE_API,
        provider=option.provider,
        model=option.model,
        model_snapshot=option.model,
        adapter_id="dashscope-qwen-image",
        adapter_version="test",
        protocol_version="dashscope-multimodal-generation/v1",
        capability=option.capabilities,
        model_option=option,
        estimated_cost_micros=option.unit_cost_micros,
        cost_estimate_known=True,
        cost_source=GenerationCostSource.CONFIGURED_RATE,
    )
    adapter = DashScopeQwenImageAdapter(
        identity=identity,
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        max_attempts=1,
        transport=httpx.MockTransport(handler),
        download_transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        adapter.generate(
            AdapterRequest(
                request_id=uuid4(),
                run_root=tmp_path / "run",
                project=_project(),
                shot=_shot(),
                input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
                source_path=source,
                source_sha256="a" * 64,
                references=(),
                candidate_count=1,
                width=720,
                height=1280,
                positive_prompt="保持构图，替换人物",
                negative_prompt="模糊",
                seed=42,
                capability=option.capabilities,
            )
        )
    )
    assert received["authorization"] == "Bearer secret"
    payload = received["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen-image-2.0-pro"
    assert payload["parameters"]["size"] == "720*1280"
    assert payload["parameters"]["seed"] == 42
    assert len(result.images) == 1
    assert result.images[0].width == 720
    assert result.provider_request_id == "provider-request-1"
    assert result.actual_cost_micros == 500_000


def test_dashscope_adapter_sends_text_only_content_for_text_to_image(
    tmp_path: Path,
) -> None:
    output_png = tmp_path / "provider-text.png"
    Image.new("RGB", (720, 1280), (50, 130, 205)).save(output_png, "PNG")
    result_url = "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/text.png"
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            received["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {"message": {"content": [{"image": result_url}]}}
                        ]
                    },
                    "usage": {"image_count": 1},
                    "request_id": "text-to-image-request",
                },
            )
        return httpx.Response(200, content=output_png.read_bytes())

    option = load_image_model_catalog().option("qwen_image_2_pro")
    identity = AdapterIdentity(
        execution_mode=ImageExecutionMode.REMOTE_API,
        provider=option.provider,
        model=option.model,
        model_snapshot=option.model,
        adapter_id="dashscope-qwen-image",
        adapter_version="test",
        protocol_version="dashscope-multimodal-generation/v1",
        capability=option.capabilities,
        model_option=option,
        estimated_cost_micros=option.unit_cost_micros,
        cost_estimate_known=True,
        cost_source=GenerationCostSource.CONFIGURED_RATE,
    )
    adapter = DashScopeQwenImageAdapter(
        identity=identity,
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        max_attempts=1,
        transport=httpx.MockTransport(handler),
        download_transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        adapter.generate(
            AdapterRequest(
                request_id=uuid4(),
                run_root=tmp_path / "run-text",
                project=_project(),
                shot=_shot(),
                input_mode=ImageGenerationInputMode.TEXT_TO_IMAGE,
                source_path=None,
                source_sha256=None,
                references=(),
                candidate_count=1,
                width=720,
                height=1280,
                positive_prompt="雨夜中的霓虹街道",
                negative_prompt="模糊",
                seed=None,
                capability=option.capabilities,
            )
        )
    )

    payload = received["payload"]
    assert isinstance(payload, dict)
    content = payload["input"]["messages"][0]["content"]
    assert content == [{"text": "雨夜中的霓虹街道"}]
    assert len(result.images) == 1


def test_local_tool_detection_and_gateway_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(workspace_root))
    fake_tool = write_fake_tool(tmp_path)
    detection = asyncio.run(
        detect_local_tool(
            sys.executable,
            [str(fake_tool)],
            timeout_seconds=20,
        )
    )
    assert detection.tool_id == "fake-imagegen"
    assert detection.tool_version == "1.2.3"
    assert detection.capability.max_reference_images == 4

    settings = ImageGenerationSettingsService()
    saved = asyncio.run(
        settings.update(
            ImageGenerationSettingsUpdate(
                execution_mode="local_tool",
                local_executable_path=sys.executable,
                local_fixed_args=[str(fake_tool)],
                local_cost_source="unknown",
                local_proxy_mode="manual",
                local_proxy_url="http://127.0.0.1:10808",
            )
        )
    )
    assert saved.enabled is True
    assert saved.local_tool_id == "fake-imagegen"
    assert saved.local_proxy_effective_url == "http://127.0.0.1:10808"
    assert saved.local_proxy_source == "manual"

    workspace = WorkspaceManager()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)
    source = write_image(tmp_path / "source.jpg")
    shot = _shot(project.id)
    gateway = ImageGenerationGateway(workspace, settings)
    run, candidates = asyncio.run(
        gateway.generate(
            project,
            shot,
            shot.revision_id,
            [],
            [],
            candidate_count=2,
            source_path=source,
            allow_unknown_cost=True,
        )
    )
    assert run.status == "completed"
    assert run.execution_mode == ImageExecutionMode.LOCAL_TOOL
    assert run.model == "fake-imagegen"
    assert run.cost_source == GenerationCostSource.UNKNOWN
    assert run.cost_estimate_known is False
    assert run.usage["https_proxy"] == "http://127.0.0.1:10808"
    assert len(candidates) == 2
    assert all(is_file(workspace.resolve(item.relative_path)) for item in candidates)
    assert candidates[0].quality_report["automated_checks"]["file_integrity"]["status"] == "passed"
    assert candidates[0].quality_report["status"] in {
        "manual_review_required",
        "warning",
    }
    assert is_file(workspace.resolve(run.input_snapshot_relative_path))
    assert is_file(workspace.resolve(run.output_manifest_relative_path or ""))


def test_local_tool_supports_pure_text_generation_without_image_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    fake_tool = write_fake_tool(tmp_path)
    settings = ImageGenerationSettingsService()
    asyncio.run(
        settings.update(
            ImageGenerationSettingsUpdate(
                execution_mode="local_tool",
                local_executable_path=sys.executable,
                local_fixed_args=[str(fake_tool)],
                local_cost_source="unmetered",
            )
        )
    )
    workspace = WorkspaceManager()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)
    run, candidates = asyncio.run(
        ImageGenerationGateway(workspace, settings).generate(
            project,
            _shot(project.id),
            uuid4(),
            [],
            [],
            candidate_count=1,
            source_path=None,
            input_mode=ImageGenerationInputMode.TEXT_TO_IMAGE,
        )
    )

    assert run.status == "completed"
    assert run.input_mode == ImageGenerationInputMode.TEXT_TO_IMAGE
    assert len(candidates) == 1
    snapshot = json.loads(
        filesystem_path(
            workspace.resolve(run.input_snapshot_relative_path)
        ).read_text("utf-8")
    )
    assert snapshot["input_mode"] == "text_to_image"
    assert snapshot["source"] is None
    assert snapshot["references"] == []


def test_identity_reference_is_second_input_and_exclusive_identity_source() -> None:
    project = _project()
    shot = _shot(project.id)
    identity_asset = ReferenceAsset(
        project_id=project.id,
        type=ReferenceAssetType.PERSON,
        name="唯一人物",
        relative_path="references/identity.jpg",
        mime_type="image/jpeg",
        width=720,
        height=1280,
        sha256="a" * 64,
        rights_confirmed=True,
    )
    scene_asset = ReferenceAsset(
        project_id=project.id,
        type=ReferenceAssetType.SCENE,
        name="场景参考",
        relative_path="references/scene.jpg",
        mime_type="image/jpeg",
        width=720,
        height=1280,
        sha256="b" * 64,
        rights_confirmed=True,
    )
    bindings = [
        ReferenceBinding(
            shot_plan_id=shot.id,
            reference_asset_id=scene_asset.id,
            role=ReferenceRole.SCENE,
            weight=2,
        ),
        ReferenceBinding(
            shot_plan_id=shot.id,
            reference_asset_id=identity_asset.id,
            role=ReferenceRole.IDENTITY,
            weight=0.1,
        ),
    ]
    references = build_reference_inputs(
        bindings,
        [scene_asset, identity_asset],
        resolve_path=Path,
    )
    request = ImageGenerationRequest(
        project=project,
        shot=shot,
        revision_id=uuid4(),
        input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
        source_path=Path("source.jpg"),
        source_sha256="c" * 64,
        references=references,
        candidate_count=1,
        execution_mode=ImageExecutionMode.LOCAL_TOOL,
    )

    assert [item.role for item in references] == ["identity", "scene"]
    manifest = build_input_manifest(source_present=True, references=references)
    assert manifest[0]["input_index"] == 1
    assert manifest[0]["identity_source"] is False
    assert manifest[1]["input_index"] == 2
    assert manifest[1]["asset_id"] == str(identity_asset.id)
    assert manifest[1]["responsibility"] == "exclusive_person_identity_source"
    positive = _compiled_prompt(request)
    negative = _negative_prompt(request)
    assert "图像2" in positive
    assert "唯一来源" in positive
    assert "严禁从图像1继承人物的年龄、五官、脸型、肤色、发型、身份" in positive
    assert "身份一律服从图像2" in positive
    assert "混合图像1与图像2的人脸或身份" in negative
    assert "生成第三个人物身份" in negative


def test_identity_reference_forbids_text_to_image_and_multiple_identities() -> None:
    project = _project()
    shot = _shot(project.id)
    first = ReferenceAsset(
        project_id=project.id,
        type=ReferenceAssetType.PERSON,
        name="人物一",
        relative_path="references/first.jpg",
        mime_type="image/jpeg",
        width=720,
        height=1280,
        sha256="a" * 64,
        rights_confirmed=True,
    )
    second = first.model_copy(
        update={"id": uuid4(), "name": "人物二", "sha256": "b" * 64}
    )
    first_binding = ReferenceBinding(
        shot_plan_id=shot.id,
        reference_asset_id=first.id,
        role=ReferenceRole.IDENTITY,
    )
    state = validate_identity_bindings([first_binding], [first])
    with pytest.raises(IdentityPolicyViolation) as text_error:
        validate_identity_generation(
            state=state,
            input_mode=ImageGenerationInputMode.TEXT_TO_IMAGE,
            source_present=False,
        )
    assert text_error.value.code == "identity_requires_reference_mode"

    with pytest.raises(IdentityPolicyViolation) as duplicate_error:
        validate_identity_bindings(
            [
                first_binding,
                ReferenceBinding(
                    shot_plan_id=shot.id,
                    reference_asset_id=second.id,
                    role=ReferenceRole.IDENTITY,
                ),
            ],
            [first, second],
        )
    assert duplicate_error.value.code == "multiple_identity_references"

    with pytest.raises(IdentityPolicyViolation) as missing_asset_error:
        validate_identity_bindings([first_binding], [])
    assert missing_asset_error.value.code == "identity_asset_missing"

    with pytest.raises(IdentityPolicyViolation) as missing_input_error:
        validate_identity_generation(
            state=state,
            input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
            source_present=True,
            references=(
                ImageReferenceInput(
                    asset_id=second.id,
                    name="错误人物",
                    role=ReferenceRole.IDENTITY.value,
                    path=Path("second.jpg"),
                    relative_path="references/second.jpg",
                    sha256="b" * 64,
                    weight=1,
                ),
            ),
            capability=ImageGenerationCapability(),
        )
    assert missing_input_error.value.code == "identity_reference_missing"


def test_gateway_reuses_verified_candidates_without_repeat_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    fake_tool = write_fake_tool(tmp_path)
    settings = ImageGenerationSettingsService()
    asyncio.run(
        settings.update(
            ImageGenerationSettingsUpdate(
                execution_mode="local_tool",
                local_executable_path=sys.executable,
                local_fixed_args=[str(fake_tool)],
                local_cost_source="unknown",
            )
        )
    )
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)
    source = write_image(tmp_path / "source.jpg")
    shot = _shot(project.id)
    gateway = ImageGenerationGateway(
        workspace,
        settings,
        repository=repository,
    )

    async def exercise_cache():
        first_run, first_candidates = await gateway.generate(
            project,
            shot,
            uuid4(),
            [],
            [],
            candidate_count=2,
            source_path=source,
            allow_unknown_cost=True,
        )
        await repository.save_generation_run(first_run)
        for candidate in first_candidates:
            await repository.save_generation_candidate(candidate)
        second_run, second_candidates = await gateway.generate(
            project,
            shot,
            uuid4(),
            [],
            [],
            candidate_count=2,
            source_path=source,
            allow_unknown_cost=False,
        )
        variation_run, variation_candidates = await gateway.generate(
            project,
            shot,
            uuid4(),
            [],
            [],
            candidate_count=2,
            source_path=source,
            allow_unknown_cost=True,
            seed=8675309,
            reuse_cache=False,
        )
        return (
            first_run,
            first_candidates,
            second_run,
            second_candidates,
            variation_run,
            variation_candidates,
        )

    (
        first_run,
        first_candidates,
        second_run,
        second_candidates,
        variation_run,
        variation_candidates,
    ) = asyncio.run(exercise_cache())
    assert first_run.status == "completed"
    assert second_run.status == "cached"
    assert second_run.request_fingerprint == first_run.request_fingerprint
    assert second_run.actual_cost_micros == 0
    assert second_run.estimated_cost_micros == 0
    assert second_run.usage["source_run_id"] == str(first_run.id)
    assert [item.id for item in second_candidates] != [
        item.id for item in first_candidates
    ]
    assert [item.relative_path for item in second_candidates] == [
        item.relative_path for item in first_candidates
    ]
    assert variation_run.status == "completed"
    assert variation_run.request_fingerprint != first_run.request_fingerprint
    assert [item.relative_path for item in variation_candidates] != [
        item.relative_path for item in first_candidates
    ]


def test_local_unknown_cost_requires_explicit_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    fake_tool = write_fake_tool(tmp_path)
    settings = ImageGenerationSettingsService()
    asyncio.run(
        settings.update(
            ImageGenerationSettingsUpdate(
                execution_mode="local_tool",
                local_executable_path=sys.executable,
                local_fixed_args=[str(fake_tool)],
                local_cost_source="unknown",
            )
        )
    )
    workspace = WorkspaceManager()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)
    with pytest.raises(Exception, match="未知成本"):
        asyncio.run(
            ImageGenerationGateway(workspace, settings).generate(
                project,
                _shot(project.id),
                uuid4(),
                [],
                [],
                candidate_count=1,
                source_path=write_image(tmp_path / "source.jpg"),
            )
        )


def test_subscription_quota_does_not_require_unknown_cost_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    fake_tool = write_fake_tool(tmp_path)
    settings = ImageGenerationSettingsService()
    saved = asyncio.run(
        settings.update(
            ImageGenerationSettingsUpdate(
                execution_mode="local_tool",
                local_executable_path=sys.executable,
                local_fixed_args=[str(fake_tool)],
                local_cost_source="subscription_quota",
            )
        )
    )
    assert saved.local_cost_source == GenerationCostSource.SUBSCRIPTION_QUOTA

    workspace = WorkspaceManager()
    project = _project()
    workspace.initialize_production(project.record_id, project.id)
    run, candidates = asyncio.run(
        ImageGenerationGateway(workspace, settings).generate(
            project,
            _shot(project.id),
            uuid4(),
            [],
            [],
            candidate_count=1,
            source_path=write_image(tmp_path / "source.jpg"),
        )
    )
    assert run.status == "completed"
    assert run.cost_source == GenerationCostSource.SUBSCRIPTION_QUOTA
    assert run.cost_estimate_known is False
    assert run.actual_cost_micros == 0
    assert len(candidates) == 1


def test_codex_discovery_is_read_only_and_recommends_latest_flagship(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"test")
    skill = tmp_path / "imagegen" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("test", "utf-8")
    wrapper = tmp_path / "codex_imagegen_adapter.py"
    wrapper.write_text("test", "utf-8")
    monkeypatch.setattr(codex_local, "find_codex_executable", lambda: executable)
    monkeypatch.setattr(codex_local, "codex_version", lambda _path: "codex-cli 0.146.0")
    monkeypatch.setattr(codex_local, "codex_auth_status", lambda _path: "authenticated")
    monkeypatch.setattr(codex_local, "imagegen_skill_path", lambda: skill)
    monkeypatch.setattr(codex_local, "desktop_app_found", lambda: True)
    monkeypatch.setattr(codex_local, "wrapper_path", lambda: wrapper)

    result = codex_local.discover_codex_environment_sync()
    assert result.can_auto_configure is True
    assert result.codex_executable_path == str(executable)
    assert result.auth_status == "authenticated"
    assert result.imagegen_status == "installed_unverified"
    assert result.recommended_model == "gpt-5.6-sol"
    assert result.recommended_reasoning_effort == "xhigh"
    assert result.requires_smoke_test is True
    assert result.warnings == []


def test_codex_auto_configuration_persists_wrapper_and_model_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "codex_imagegen_adapter.py"

    async def discovery() -> LocalCodexDiscoveryResponse:
        return LocalCodexDiscoveryResponse(
            codex_found=True,
            codex_executable_path=sys.executable,
            codex_version="codex-cli 0.146.0",
            auth_status="authenticated",
            desktop_app_found=True,
            imagegen_status="installed_unverified",
            imagegen_skill_path=str(tmp_path / "SKILL.md"),
            recommended_model="gpt-5.6-sol",
            model_catalog_version="test-catalog",
            wrapper_path=str(wrapper),
            can_auto_configure=True,
        )

    preflight_calls: list[tuple[str, list[str], dict[str, object]]] = []

    async def sandbox_preflight(
        executable_path: str,
        fixed_args: list[str],
        **kwargs: object,
    ) -> CodexSandboxPreflightResult:
        preflight_calls.append((executable_path, fixed_args, kwargs))
        return CodexSandboxPreflightResult(latency_ms=7)

    service = ImageGenerationSettingsService(
        codex_discovery=discovery,
        codex_sandbox_preflight=sandbox_preflight,
    )
    saved = asyncio.run(
        service.auto_configure_codex(
            LocalCodexAutoConfigureRequest(
                model_policy="latest_flagship",
                reasoning_effort="xhigh",
                default_candidate_count=3,
                windows_sandbox_mode="unelevated",
            )
        )
    )
    assert saved.execution_mode == ImageExecutionMode.LOCAL_TOOL
    assert saved.local_adapter_id == "codex_imagegen_v1"
    assert saved.local_model_policy == "latest_flagship"
    assert saved.local_model == "gpt-5.6-sol"
    assert saved.local_reasoning_effort == "xhigh"
    assert saved.local_windows_sandbox_mode == "unelevated"
    assert saved.local_cost_source == GenerationCostSource.SUBSCRIPTION_QUOTA
    assert saved.local_tool_id == "openai-codex-imagegen"
    assert saved.default_candidate_count == 3
    assert "--model" in saved.local_fixed_args
    assert "gpt-5.6-sol" in saved.local_fixed_args
    assert "--windows-sandbox-mode" in saved.local_fixed_args
    assert "unelevated" in saved.local_fixed_args
    assert len(preflight_calls) == 1
    assert preflight_calls[0][0] == sys.executable
    assert preflight_calls[0][2]["timeout_seconds"] == 45
    persisted = (tmp_path / ".env.local").read_text("utf-8")
    assert "VIRAL_DNA_IMAGE_LOCAL_MODEL=gpt-5.6-sol" in persisted
    assert "VIRAL_DNA_IMAGE_LOCAL_COST_SOURCE=subscription_quota" in persisted
    assert "VIRAL_DNA_IMAGE_LOCAL_WINDOWS_SANDBOX_MODE=unelevated" in persisted


def test_codex_network_probe_uses_selected_proxy_and_reports_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_image_settings(tmp_path, monkeypatch)
    calls: list[tuple[str | None, int]] = []

    async def discovery() -> LocalCodexDiscoveryResponse:
        return LocalCodexDiscoveryResponse(
            codex_found=True,
            codex_executable_path=sys.executable,
            codex_version="codex-cli test",
            auth_status="authenticated",
            imagegen_status="installed_unverified",
            model_catalog_version="test-catalog",
            wrapper_path=str(tmp_path / "wrapper.py"),
        )

    async def network_probe(
        proxy_url: str | None,
        timeout_seconds: int,
    ) -> codex_local.CodexNetworkProbeResult:
        calls.append((proxy_url, timeout_seconds))
        return codex_local.CodexNetworkProbeResult(
            reachable=True,
            http_status=401,
            latency_ms=18,
            message="connected",
        )

    service = ImageGenerationSettingsService(
        codex_discovery=discovery,
        codex_network_probe=network_probe,
    )
    result = asyncio.run(
        service.test_codex_network(
            LocalCodexNetworkTestRequest(
                proxy_mode="manual",
                proxy_url="127.0.0.1:10808",
                timeout_seconds=9,
            )
        )
    )

    assert calls == [("http://127.0.0.1:10808", 9)]
    assert result.reachable is True
    assert result.auth_status == "authenticated"
    assert result.proxy_source == "manual"
    assert result.effective_proxy_url == "http://127.0.0.1:10808"
    assert "可以执行本机 ImageGen" in result.message


def test_codex_windows_system_proxy_is_not_reinjected_into_child_process() -> None:
    proxy_url = "http://127.0.0.1:10808"

    assert codex_local.local_tool_proxy_environment_url(
        codex_local.CODEX_IMAGEGEN_ADAPTER_ID,
        "system",
        proxy_url,
        "windows_user_proxy",
    ) is None
    assert codex_local.local_tool_proxy_delivery(
        codex_local.CODEX_IMAGEGEN_ADAPTER_ID,
        "system",
        proxy_url,
        "windows_user_proxy",
    ) == "codex_native"
    assert codex_local.local_tool_proxy_environment_url(
        codex_local.CODEX_IMAGEGEN_ADAPTER_ID,
        "manual",
        proxy_url,
        "manual",
    ) == proxy_url
    assert codex_local.local_tool_proxy_environment_url(
        codex_local.CODEX_IMAGEGEN_ADAPTER_ID,
        "system",
        proxy_url,
        "environment",
    ) == proxy_url
    assert codex_local.local_tool_proxy_environment_url(
        "custom-image-tool",
        "system",
        proxy_url,
        "windows_user_proxy",
    ) == proxy_url


def test_codex_sandbox_preflight_uses_selected_mode_without_model_call(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "codex_imagegen_adapter.py"
    fake_codex = write_fake_codex(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--codex-executable",
            sys.executable,
            "--codex-fixed-arg",
            str(fake_codex),
            "--windows-sandbox-mode",
            "unelevated",
            "preflight",
            "--cwd",
            str(tmp_path),
            "--timeout",
            "15",
        ],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
        timeout=30,
    )

    payload = json.loads(result.stdout)
    argv = json.loads((tmp_path / "codex-sandbox-argv.json").read_text("utf-8"))
    assert payload["ready"] is True
    assert payload["windows_sandbox_mode"] == "unelevated"
    assert "sandbox" in argv
    assert "exec" not in argv
    assert argv[argv.index("--permission-profile") + 1] == ":workspace"
    assert 'windows.sandbox="unelevated"' in argv


def test_codex_sandbox_service_reports_delivery_and_never_generates(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "codex_imagegen_adapter.py"

    async def discovery() -> LocalCodexDiscoveryResponse:
        return LocalCodexDiscoveryResponse(
            codex_found=True,
            codex_executable_path=sys.executable,
            codex_version="codex-cli test",
            auth_status="authenticated",
            imagegen_status="installed_unverified",
            model_catalog_version="test-catalog",
            wrapper_path=str(wrapper),
        )

    calls: list[tuple[str, list[str], dict[str, object]]] = []

    async def sandbox_preflight(
        executable_path: str,
        fixed_args: list[str],
        **kwargs: object,
    ) -> CodexSandboxPreflightResult:
        calls.append((executable_path, fixed_args, kwargs))
        return CodexSandboxPreflightResult(latency_ms=11)

    service = ImageGenerationSettingsService(
        codex_discovery=discovery,
        codex_sandbox_preflight=sandbox_preflight,
    )
    result = asyncio.run(
        service.test_codex_sandbox(
            LocalCodexSandboxTestRequest(
                proxy_mode="manual",
                proxy_url="127.0.0.1:10808",
                windows_sandbox_mode="unelevated",
                timeout_seconds=20,
            )
        )
    )

    assert result.ready is True
    assert result.sandbox_mode == "unelevated"
    assert result.proxy_delivery == "environment"
    assert result.latency_ms == 11
    assert calls[0][0] == sys.executable
    assert calls[0][2]["proxy_url"] == "http://127.0.0.1:10808"
    assert "--windows-sandbox-mode" in calls[0][1]
    assert "unelevated" in calls[0][1]


def test_codex_sandbox_setup_error_is_actionable_and_not_retryable() -> None:
    error = _codex_windows_sandbox_error(
        "codex-windows-sandbox-setup.exe：找不到指定的模块。"
    )

    assert error is not None
    assert error.code == "codex_windows_sandbox_setup_failed"
    assert error.retryable is False
    assert "兼容模式（unelevated）" in str(error)


def test_codex_imagegen_wrapper_protocol_with_fake_codex(tmp_path: Path) -> None:
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "codex_imagegen_adapter.py"
    fake_codex = write_fake_codex(tmp_path)
    run_root = tmp_path / "run"
    source = write_image(run_root / "tool-inputs" / "source.jpg", size=(320, 576))
    request_path = run_root / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "protocol_version": "viral-dna-image-tool/v1",
                "request_id": str(uuid4()),
                "candidate_count": 1,
                "output": {"width": 320, "height": 576},
                "prompt": {"positive": "保持构图", "negative": "模糊"},
                "inputs": [
                    {
                        "role": "source",
                        "path": source.relative_to(run_root).as_posix(),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    output_root = run_root / "tool-output"
    result = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--codex-executable",
            sys.executable,
            "--codex-fixed-arg",
            str(fake_codex),
            "--model",
            "gpt-5.6-sol",
            "--reasoning-effort",
            "xhigh",
            "generate",
            "--request",
            str(request_path),
            "--output",
            str(output_root),
        ],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
        timeout=30,
    )
    manifest = json.loads((output_root / "result.json").read_text("utf-8"))
    assert result.returncode == 0
    assert manifest["status"] == "completed"
    assert manifest["tool_id"] == "openai-codex-imagegen"
    assert manifest["usage"]["model"] == "gpt-5.6-sol"
    assert manifest["usage"]["cost_source"] == "subscription_quota"
    assert manifest["candidates"][0]["path"] == "codex-candidate.png"
    argv = json.loads((run_root / "codex-exec-argv.json").read_text("utf-8"))
    assert "--ignore-user-config" in argv


def _project() -> ProductionProject:
    return ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="图片生成测试方案",
        output_aspect_ratio="9:16",
        output_width=720,
        output_height=1280,
        budget_limit_micros=10_000_000,
    )


def _shot(project_id=None) -> ShotPlan:
    return ShotPlan(
        project_id=project_id or uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-001",
        index=1,
        source_keyframe_url="/api/v1/analyses/test/artifacts/shot.jpg",
        start_seconds=0,
        end_seconds=3,
        duration_seconds=3,
        image_prompt="保持原构图，将人物替换为参考人物，真实自然光。",
    )


def _unused_reference(project_id, shot_id, path: Path) -> tuple[ReferenceAsset, ReferenceBinding]:
    asset = ReferenceAsset(
        project_id=project_id,
        type=ReferenceAssetType.PERSON,
        name="人物参考",
        relative_path=path.as_posix(),
        mime_type="image/jpeg",
        width=720,
        height=1280,
        sha256="a" * 64,
        rights_confirmed=True,
    )
    return asset, ReferenceBinding(
        shot_plan_id=shot_id,
        reference_asset_id=asset.id,
        role=ReferenceRole.IDENTITY,
    )
