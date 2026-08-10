from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from ..runtime_config import get_config_value, local_env_path
from .models import PlatformConnectionState


class PlatformConnectionRepositoryError(RuntimeError):
    pass


class PlatformConnectionRepository(Protocol):
    async def load(self) -> PlatformConnectionState: ...

    async def save(self, state: PlatformConnectionState) -> None: ...


class InMemoryPlatformConnectionRepository:
    def __init__(self) -> None:
        self._state = PlatformConnectionState()
        self._lock = asyncio.Lock()

    async def load(self) -> PlatformConnectionState:
        async with self._lock:
            return PlatformConnectionState.model_validate(self._state.model_dump(mode="json"))

    async def save(self, state: PlatformConnectionState) -> None:
        async with self._lock:
            self._state = PlatformConnectionState.model_validate(state.model_dump(mode="json"))


class LocalPlatformConnectionRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = asyncio.Lock()

    async def load(self) -> PlatformConnectionState:
        async with self._lock:
            return await asyncio.to_thread(self._read)

    async def save(self, state: PlatformConnectionState) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write, state)

    def _read(self) -> PlatformConnectionState:
        if not self.path.is_file():
            return PlatformConnectionState()
        try:
            payload = json.loads(self.path.read_text("utf-8-sig"))
            return PlatformConnectionState.model_validate(payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise PlatformConnectionRepositoryError("无法读取本机平台连接配置") from exc

    def _write(self, state: PlatformConnectionState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            temporary_path = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(
                    json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            if os.name != "nt":
                self.path.chmod(0o600)
        except OSError as exc:
            raise PlatformConnectionRepositoryError("无法保存本机平台连接配置") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def default_platform_connection_path() -> Path:
    configured = get_config_value("VIRAL_DNA_PLATFORM_CONNECTIONS_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    app_data = os.getenv("LOCALAPPDATA", "").strip() or os.getenv("APPDATA", "").strip()
    if app_data:
        return (Path(app_data) / "ViralDNA" / "platform-connections.json").resolve()
    return (local_env_path().parent / ".viraldna" / "platform-connections.json").resolve()


def create_platform_connection_repository() -> PlatformConnectionRepository:
    if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
        return InMemoryPlatformConnectionRepository()
    return LocalPlatformConnectionRepository(default_platform_connection_path())
