from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from ..models import ModelTargetSnapshot, ModelTask, ModelUsage

ResultT = TypeVar("ResultT", bound=BaseModel)


class ModelProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        provider_request_id: str | None = None,
        status_code: int | None = None,
        usage: ModelUsage | None = None,
        resolved_model: str | None = None,
        latency_ms: int = 0,
        raw_content: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider_request_id = provider_request_id
        self.status_code = status_code
        self.usage = usage
        self.resolved_model = resolved_model
        self.latency_ms = latency_ms
        self.raw_content = raw_content


class ModelProviderUnavailable(ModelProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("model_provider_unavailable", message, retryable=False)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: ModelTask
    target: ModelTargetSnapshot
    system_prompt: str
    user_prompt: str
    image_paths: tuple[Path, ...] = ()
    image_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[ResultT]):
    data: ResultT
    usage: ModelUsage
    requested_model: str
    resolved_model: str
    provider_request_id: str | None
    latency_ms: int
    raw_content: str


class StructuredModelProvider(Protocol):
    provider_id: str

    async def generate(
        self,
        request: ModelRequest,
        response_schema: type[ResultT],
    ) -> ProviderResult[ResultT]: ...
