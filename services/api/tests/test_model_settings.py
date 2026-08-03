from __future__ import annotations

from pathlib import Path

import pytest

from viral_dna_api.ai.contracts import ModelProviderError
from viral_dna_api.ai.providers.dashscope import CredentialValidationResult
from viral_dna_api.model_settings import ModelSettingsService, ModelSettingsServiceError
from viral_dna_api.models import ModelSettingsUpdate, ModelUsage


def _isolate_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    env_path = tmp_path / ".env.local"
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
    for name in (
        "VIRAL_DNA_VLM_PROVIDER",
        "VIRAL_DNA_VLM_MODEL_ALIAS",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "VIRAL_DNA_MODEL_LAST_VALIDATED_AT",
    ):
        monkeypatch.delenv(name, raising=False)
    return env_path


@pytest.mark.asyncio
async def test_valid_key_is_persisted_only_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _isolate_runtime_config(tmp_path, monkeypatch)
    captured: dict[str, str] = {}

    class SuccessfulValidator:
        async def validate_credentials(self, model: str) -> CredentialValidationResult:
            captured["model"] = model
            return CredentialValidationResult(
                requested_model=model,
                resolved_model=model,
                provider_request_id="validation-request",
                latency_ms=37,
                usage=ModelUsage(input_tokens=8, output_tokens=1, total_tokens=9),
            )

    def provider_factory(api_key: str, base_url: str) -> SuccessfulValidator:
        captured.update(api_key=api_key, base_url=base_url)
        return SuccessfulValidator()

    response = await ModelSettingsService(provider_factory).update(
        ModelSettingsUpdate(
            provider="dashscope",
            model_alias="qwen36flash",
            api_key="sk-private-example",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )

    content = env_path.read_text(encoding="utf-8")
    assert captured["api_key"] == "sk-private-example"
    assert captured["model"] == "qwen3.6-flash-2026-04-16"
    assert "VIRAL_DNA_VLM_MODEL_ALIAS=qwen36flash" in content
    assert "DASHSCOPE_API_KEY=sk-private-example" in content
    assert response.api_key_configured is True
    assert response.api_key_hint == "••••••••mple"
    assert response.validation_latency_ms == 37
    assert "sk-private-example" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_invalid_key_does_not_modify_local_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _isolate_runtime_config(tmp_path, monkeypatch)
    env_path.write_text("KEEP_ME=yes\n", encoding="utf-8")

    class RejectedValidator:
        async def validate_credentials(self, model: str) -> CredentialValidationResult:
            raise ModelProviderError(
                "model_http_error",
                "InvalidApiKey",
                retryable=False,
                status_code=401,
            )

    service = ModelSettingsService(lambda api_key, base_url: RejectedValidator())
    with pytest.raises(ModelSettingsServiceError, match="API Key 无效") as raised:
        await service.update(
            ModelSettingsUpdate(
                provider="dashscope",
                model_alias="auto",
                api_key="wrong-secret",
            )
        )

    assert raised.value.status_code == 422
    assert env_path.read_text(encoding="utf-8") == "KEEP_ME=yes\n"


@pytest.mark.asyncio
async def test_blank_key_reuses_existing_secret_without_returning_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _isolate_runtime_config(tmp_path, monkeypatch)
    env_path.write_text("DASHSCOPE_API_KEY=existing-private-key\n", encoding="utf-8")
    captured: dict[str, str] = {}

    class SuccessfulValidator:
        async def validate_credentials(self, model: str) -> CredentialValidationResult:
            return CredentialValidationResult(
                requested_model=model,
                resolved_model=model,
                provider_request_id=None,
                latency_ms=12,
                usage=ModelUsage(),
            )

    def provider_factory(api_key: str, base_url: str) -> SuccessfulValidator:
        captured["api_key"] = api_key
        return SuccessfulValidator()

    response = await ModelSettingsService(provider_factory).update(
        ModelSettingsUpdate(provider="dashscope", model_alias="auto", api_key=None)
    )

    assert captured["api_key"] == "existing-private-key"
    assert "existing-private-key" not in response.model_dump_json()
    assert response.model_alias == "auto"


@pytest.mark.asyncio
async def test_rejects_non_official_endpoint_before_sending_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_runtime_config(tmp_path, monkeypatch)
    factory_called = False

    def provider_factory(api_key: str, base_url: str):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("provider must not be constructed")

    service = ModelSettingsService(provider_factory)
    with pytest.raises(ModelSettingsServiceError, match="保护 API Key"):
        await service.update(
            ModelSettingsUpdate(
                provider="dashscope",
                model_alias="auto",
                api_key="never-send-this",
                base_url="https://evil.example/compatible-mode/v1",
            )
        )
    assert factory_called is False
