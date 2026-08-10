from __future__ import annotations

import asyncio
import ctypes
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..runtime_config import get_config_value, local_env_path
from .models import PlatformKind


class PlatformSecretStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PlatformSecretStore(Protocol):
    @property
    def available(self) -> bool: ...

    async def save(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
        payload: bytes,
    ) -> None: ...

    async def read(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> bytes: ...

    async def delete(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> None: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDpapiSecretStore:
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return os.name == "nt"

    async def save(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
        payload: bytes,
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save, account_id, device_id, platform, payload)

    async def read(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> bytes:
        async with self._lock:
            return await asyncio.to_thread(self._read, account_id, device_id, platform)

    async def delete(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._path(account_id, device_id, platform).unlink,
                missing_ok=True,
            )

    def _path(self, account_id: UUID, device_id: UUID, platform: PlatformKind) -> Path:
        return self.root / str(account_id) / str(device_id) / f"{platform.value}.dpapi"

    def _save(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
        payload: bytes,
    ) -> None:
        if not self.available:
            raise PlatformSecretStoreError(
                "platform_secret_store_unavailable",
                "当前系统尚不支持本地加密 Cookie 存储",
            )
        protected = self._protect(payload)
        target = self._path(account_id, device_id, platform)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
            temporary_path = Path(raw_path)
            with os.fdopen(descriptor, "wb") as output:
                output.write(protected)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        except OSError as exc:
            raise PlatformSecretStoreError(
                "platform_secret_save_failed",
                "无法保存本机平台登录信息",
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _read(self, account_id: UUID, device_id: UUID, platform: PlatformKind) -> bytes:
        if not self.available:
            raise PlatformSecretStoreError(
                "platform_secret_store_unavailable",
                "当前系统尚不支持本地加密 Cookie 存储",
            )
        target = self._path(account_id, device_id, platform)
        if not target.is_file():
            raise PlatformSecretStoreError(
                "platform_cookie_secret_missing",
                "本机保存的平台登录信息不存在，请重新配置",
            )
        try:
            protected = target.read_bytes()
        except OSError as exc:
            raise PlatformSecretStoreError(
                "platform_secret_read_failed",
                "无法读取本机平台登录信息",
            ) from exc
        return self._unprotect(protected)

    @staticmethod
    def _blob(payload: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(payload, len(payload))
        blob = _DataBlob(
            len(payload),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    @staticmethod
    def _windows_apis():
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        data_blob_pointer = ctypes.POINTER(_DataBlob)
        crypt32.CryptProtectData.argtypes = [
            data_blob_pointer,
            wintypes.LPCWSTR,
            data_blob_pointer,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            data_blob_pointer,
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            data_blob_pointer,
            wintypes.LPVOID,
            data_blob_pointer,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            data_blob_pointer,
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        return crypt32, kernel32

    def _protect(self, payload: bytes) -> bytes:
        source, source_buffer = self._blob(payload)
        output = _DataBlob()
        crypt32, kernel32 = self._windows_apis()
        success = crypt32.CryptProtectData(
            ctypes.byref(source),
            "ViralDNA platform cookie",
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise PlatformSecretStoreError(
                "platform_secret_encrypt_failed",
                "Windows 无法加密平台登录信息",
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))

    def _unprotect(self, payload: bytes) -> bytes:
        source, source_buffer = self._blob(payload)
        output = _DataBlob()
        crypt32, kernel32 = self._windows_apis()
        success = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise PlatformSecretStoreError(
                "platform_secret_decrypt_failed",
                "Windows 无法解密平台登录信息，请重新配置",
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))


class InMemoryPlatformSecretStore:
    def __init__(self) -> None:
        self.values: dict[tuple[UUID, UUID, PlatformKind], bytes] = {}

    @property
    def available(self) -> bool:
        return True

    async def save(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
        payload: bytes,
    ) -> None:
        self.values[(account_id, device_id, platform)] = bytes(payload)

    async def read(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> bytes:
        try:
            return bytes(self.values[(account_id, device_id, platform)])
        except KeyError as exc:
            raise PlatformSecretStoreError(
                "platform_cookie_secret_missing",
                "本机保存的平台登录信息不存在，请重新配置",
            ) from exc

    async def delete(
        self,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> None:
        self.values.pop((account_id, device_id, platform), None)


def default_platform_secret_root() -> Path:
    configured = get_config_value("VIRAL_DNA_PLATFORM_SECRET_ROOT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    app_data = os.getenv("LOCALAPPDATA", "").strip() or os.getenv("APPDATA", "").strip()
    if app_data:
        return (Path(app_data) / "ViralDNA" / "secrets" / "platforms").resolve()
    return (local_env_path().parent / ".viraldna" / "secrets" / "platforms").resolve()


def create_platform_secret_store() -> PlatformSecretStore:
    if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
        return InMemoryPlatformSecretStore()
    return WindowsDpapiSecretStore(default_platform_secret_root())
