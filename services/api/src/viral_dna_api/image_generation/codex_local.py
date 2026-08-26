from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from ..models import LocalCodexDiscoveryResponse

CODEX_MODEL_CATALOG_VERSION = "openai-model-guidance-2026-08-04"
LATEST_FLAGSHIP_MODEL = "gpt-5.6-sol"
BALANCED_MODEL = "gpt-5.6-terra"
CODEX_IMAGEGEN_ADAPTER_ID = "codex_imagegen_v1"
CODEX_NETWORK_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
CODEX_GENERATED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class CodexNetworkProbeResult:
    reachable: bool
    http_status: int | None
    latency_ms: int
    message: str


def codex_generated_images_root() -> Path:
    codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
    return (codex_home / "generated_images").resolve()


def _event_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_event_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_event_strings(item))
        return strings
    return []


def _paths_in_event_string(value: str) -> list[Path]:
    candidates = [value.strip().strip("`\"'")]
    candidates.extend(
        match.group("path")
        for match in re.finditer(
            r"(?P<path>(?:file:///|[A-Za-z]:[\\/]|/)[^\"\r\n]*?\.(?:png|jpe?g|webp))",
            value,
            flags=re.IGNORECASE,
        )
    )
    paths: list[Path] = []
    for candidate in candidates:
        normalized = candidate.strip().strip("`\"'")
        if normalized.lower().startswith("file://"):
            parsed = urlparse(normalized)
            normalized = unquote(parsed.path)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:/", normalized):
                normalized = normalized[1:]
        path = Path(normalized)
        if path.suffix.lower() in CODEX_GENERATED_IMAGE_EXTENSIONS:
            paths.append(path)
    return paths


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _event_artifact_paths(run_root: Path, generated_root: Path) -> list[Path]:
    event_path = run_root / "tool-output" / "codex-events.jsonl"
    stdout_path = run_root / "tool-output" / "codex-stdout.log"
    sources = [event_path] if event_path.is_file() else []
    if not sources and stdout_path.is_file():
        sources.append(stdout_path)
    paths: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        try:
            lines = source.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event: Any = json.loads(line)
            except json.JSONDecodeError:
                event = line
            for value in _event_strings(event):
                for path in _paths_in_event_string(value):
                    try:
                        resolved = path.resolve()
                    except OSError:
                        continue
                    key = os.path.normcase(str(resolved))
                    if (
                        key not in seen
                        and resolved.is_file()
                        and _is_within(resolved, generated_root)
                    ):
                        seen.add(key)
                        paths.append(resolved)
    return paths


def find_recoverable_codex_artifacts(
    run_root: Path,
    *,
    started_at: datetime | None,
    completed_at: datetime | None,
    expected_count: int,
    generated_root: Path | None = None,
) -> tuple[Path, ...]:
    """Find an exact, unambiguous set of ImageGen files for one failed run."""

    expected_count = max(1, min(4, int(expected_count or 1)))
    generated_root = (generated_root or codex_generated_images_root()).resolve()
    event_paths = _event_artifact_paths(run_root, generated_root)
    if len(event_paths) >= expected_count:
        return tuple(event_paths[:expected_count])
    if not generated_root.is_dir() or started_at is None or completed_at is None:
        return ()

    window_start = started_at.timestamp() - 3
    window_end = completed_at.timestamp() + 3
    grouped: dict[str, list[Path]] = {}
    try:
        candidates = generated_root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in CODEX_GENERATED_IMAGE_EXTENSIONS:
                continue
            try:
                modified_at = path.stat().st_mtime
            except OSError:
                continue
            if window_start <= modified_at <= window_end:
                resolved = path.resolve()
                grouped.setdefault(os.path.normcase(str(resolved.parent)), []).append(resolved)
    except OSError:
        return ()

    exact_groups = [
        sorted(paths, key=lambda path: path.stat().st_mtime)
        for paths in grouped.values()
        if len(paths) == expected_count
    ]
    if len(exact_groups) != 1:
        return ()
    return tuple(exact_groups[0])


def local_tool_proxy_environment_url(
    adapter_id: str,
    proxy_mode: str,
    effective_proxy_url: str | None,
    proxy_source: str,
) -> str | None:
    """Return only the proxy that should be injected into a child tool process.

    Codex 0.146+ reads the Windows user proxy itself. Re-injecting that same
    proxy through HTTP_PROXY causes the Windows sandbox helper to repeatedly
    rebuild firewall state. Manual proxies and environment-only proxies still
    need explicit delivery, as do non-Codex local tools.
    """

    if proxy_mode == "disabled" or not effective_proxy_url:
        return None
    if (
        adapter_id == CODEX_IMAGEGEN_ADAPTER_ID
        and proxy_mode == "system"
        and proxy_source == "windows_user_proxy"
    ):
        return None
    return effective_proxy_url


def local_tool_proxy_delivery(
    adapter_id: str,
    proxy_mode: str,
    effective_proxy_url: str | None,
    proxy_source: str,
) -> str:
    if proxy_mode == "disabled" or not effective_proxy_url:
        return "direct"
    if (
        adapter_id == CODEX_IMAGEGEN_ADAPTER_ID
        and proxy_mode == "system"
        and proxy_source == "windows_user_proxy"
    ):
        return "codex_native"
    return "environment"


def project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def wrapper_path() -> Path:
    return project_root() / "scripts" / "codex_imagegen_adapter.py"


def _safe_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "CODEX_HOME",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _vendor_codex_candidates(launcher: Path) -> list[Path]:
    package_root = launcher.parent / "node_modules" / "@openai" / "codex"
    if not package_root.is_dir():
        return []
    return sorted(
        package_root.glob("node_modules/@openai/codex-*/vendor/**/codex.exe"),
        key=lambda path: str(path),
    )


def find_codex_executable() -> Path | None:
    launchers: list[Path] = []
    for name in ("codex.exe", "codex.cmd", "codex"):
        resolved = shutil.which(name)
        if resolved:
            candidate = Path(resolved)
            if candidate not in launchers:
                launchers.append(candidate)
    for launcher in launchers:
        if launcher.suffix.lower() == ".exe" and launcher.is_file():
            return launcher.resolve()
        vendor = _vendor_codex_candidates(launcher)
        if vendor:
            return vendor[-1].resolve()
    return None


def _run_codex(executable: Path, *args: str, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *args],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        encoding="utf-8",
        env=_safe_environment(),
        errors="replace",
        shell=False,
        text=True,
        timeout=timeout,
    )


def codex_version(executable: Path) -> str | None:
    try:
        result = _run_codex(executable, "--version")
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output[:160] if result.returncode == 0 and output else None


def codex_auth_status(executable: Path) -> str:
    try:
        result = _run_codex(executable, "login", "status")
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0:
        return "authenticated"
    if "not logged" in output or "login" in output or "authenticate" in output:
        return "not_authenticated"
    return "unknown"


def imagegen_skill_path() -> Path | None:
    codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
    candidates = [
        codex_home / "skills" / ".system" / "imagegen" / "SKILL.md",
        codex_home / "skills" / "imagegen" / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def desktop_app_found() -> bool:
    if os.name != "nt":
        return False
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return False
    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if (Get-AppxPackage -Name OpenAI.Codex) { exit 0 } else { exit 1 }",
            ],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_safe_environment(),
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def discover_codex_environment_sync() -> LocalCodexDiscoveryResponse:
    executable = find_codex_executable()
    version = codex_version(executable) if executable else None
    auth = codex_auth_status(executable) if executable and version else "unknown"
    skill_path = imagegen_skill_path()
    adapter = wrapper_path()
    warnings: list[str] = []
    if executable is None:
        warnings.append("未找到可直接执行的 Codex CLI")
    elif version is None:
        warnings.append("Codex CLI 已找到，但版本检测失败")
    if auth == "not_authenticated":
        warnings.append("Codex CLI 尚未登录")
    elif auth == "unknown":
        warnings.append("无法无费用确认 Codex 登录状态")
    if skill_path is None:
        warnings.append("未发现本机 imagegen 技能")
    if not adapter.is_file():
        warnings.append("ViralDNA Codex ImageGen 包装器不存在")
    can_configure = bool(executable and version and skill_path and adapter.is_file())
    return LocalCodexDiscoveryResponse(
        codex_found=bool(executable and version),
        codex_executable_path=str(executable) if executable else None,
        codex_version=version,
        auth_status=auth,
        desktop_app_found=desktop_app_found(),
        imagegen_status="installed_unverified" if skill_path else "not_found",
        imagegen_skill_path=str(skill_path) if skill_path else None,
        recommended_adapter_id=CODEX_IMAGEGEN_ADAPTER_ID,
        recommended_model="gpt-5.6-sol",
        model_catalog_version=CODEX_MODEL_CATALOG_VERSION,
        wrapper_path=str(adapter),
        can_auto_configure=can_configure,
        warnings=warnings,
    )


async def discover_codex_environment() -> LocalCodexDiscoveryResponse:
    return await asyncio.to_thread(discover_codex_environment_sync)


async def probe_codex_network(
    proxy_url: str | None,
    timeout_seconds: int = 15,
) -> CodexNetworkProbeResult:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "ViralDNA-Codex-Network-Probe/1.0"},
        ) as client:
            response = await client.head(CODEX_NETWORK_ENDPOINT)
    except httpx.TimeoutException:
        return CodexNetworkProbeResult(
            False,
            None,
            max(0, round((time.perf_counter() - started) * 1000)),
            "连接 ChatGPT 超时，请检查代理是否允许 HTTPS 与 WebSocket。",
        )
    except httpx.ProxyError as exc:
        return CodexNetworkProbeResult(
            False,
            None,
            max(0, round((time.perf_counter() - started) * 1000)),
            f"无法连接本机代理：{str(exc)[:240]}",
        )
    except httpx.ConnectError as exc:
        return CodexNetworkProbeResult(
            False,
            None,
            max(0, round((time.perf_counter() - started) * 1000)),
            f"无法连接 ChatGPT：{str(exc)[:240]}",
        )
    except httpx.HTTPError as exc:
        return CodexNetworkProbeResult(
            False,
            None,
            max(0, round((time.perf_counter() - started) * 1000)),
            f"ChatGPT 网络检测失败：{str(exc)[:240]}",
        )
    return CodexNetworkProbeResult(
        True,
        response.status_code,
        max(0, round((time.perf_counter() - started) * 1000)),
        "已建立到 ChatGPT 的 HTTPS 连接。",
    )


def resolve_codex_model(policy: str, explicit_model: str | None = None) -> str:
    if policy == "balanced":
        return BALANCED_MODEL
    if policy == "pinned":
        model = (explicit_model or "").strip()
        if not model:
            raise ValueError("固定模型策略必须指定模型")
        return model
    return LATEST_FLAGSHIP_MODEL
