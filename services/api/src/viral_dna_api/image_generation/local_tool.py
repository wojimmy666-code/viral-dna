from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from ..models import GenerationCostSource, ImageGenerationCapability
from .codex_local import CODEX_IMAGEGEN_ADAPTER_ID
from .contracts import (
    LOCAL_TOOL_PROTOCOL_VERSION,
    AdapterIdentity,
    AdapterRequest,
    AdapterResult,
    GeneratedImage,
    ImageGenerationError,
    ToolDetection,
)
from .proxy import proxy_environment

MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
MAX_RESULT_JSON_BYTES = 1024 * 1024
SUPPORTED_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True, slots=True)
class CodexSandboxPreflightResult:
    latency_ms: int


def _codex_windows_sandbox_error(raw: str) -> ImageGenerationError | None:
    message = raw[-MAX_PROCESS_OUTPUT_BYTES:].strip()
    normalized = message.lower()
    markers = (
        "codex Windows 沙箱预检失败".lower(),
        "codex Windows 增强沙箱初始化失败".lower(),
        "codex-windows-sandbox-setup",
        "helper_unknown_error",
        "setup refresh had errors",
        "sandbox setup marker missing",
        "specified module could not be found",
        "找不到指定的模块",
        "offline firewall settings changed",
        "stored_ports",
        "desired_ports",
    )
    if not any(marker in normalized for marker in markers):
        return None
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    detail = lines[-1] if lines else ""
    if "兼容模式" not in detail:
        detail = (
            "Codex Windows 增强沙箱初始化失败。请在“模型与设置 → Windows 沙箱”"
            "中执行无费用预检；若自动/增强模式仍失败，请手动切换为"
            "“兼容模式（unelevated）”。兼容模式仍限制文件访问，但网络隔离较弱。"
        )
    return ImageGenerationError(
        409,
        "codex_windows_sandbox_setup_failed",
        detail[:1000],
        retryable=False,
    )


def _filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{prefix}UNC{separator}{raw[2:]}")
    return Path(f"{prefix}{raw}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".tmp-{path.name}-{os.getpid()}"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _minimal_environment(proxy_url: str | None = None) -> dict[str, str]:
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
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment.update(proxy_environment(proxy_url))
    return environment


def validate_executable_path(value: str) -> Path:
    raw = value.strip()
    if not raw:
        raise ImageGenerationError(422, "local_tool_path_required", "请填写本机工具路径")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ImageGenerationError(
            422,
            "local_tool_path_not_absolute",
            "本机工具必须使用绝对路径",
        )
    resolved = path.resolve()
    if not resolved.is_file():
        raise ImageGenerationError(422, "local_tool_not_found", "找不到本机工具可执行文件")
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        raise ImageGenerationError(422, "local_tool_not_executable", "本机工具没有执行权限")
    return resolved


def validate_fixed_args(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or len(item) > 500 or "\x00" in item or "\r" in item or "\n" in item:
            raise ImageGenerationError(
                422,
                "local_tool_argument_invalid",
                "本机工具固定参数格式无效",
            )
        normalized.append(item)
    return normalized


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    proxy_url: str | None = None,
    cancel_event: Event | None = None,
) -> tuple[int, str, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=_minimal_environment(proxy_url),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _kill_process_tree(process)
            process.communicate()
            raise ImageGenerationError(
                409,
                "generation_cancelled",
                "图片生成任务已取消",
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_process_tree(process)
            process.communicate()
            raise ImageGenerationError(
                504,
                "local_tool_timeout",
                f"本机工具执行超过 {timeout_seconds} 秒",
                retryable=True,
            )
        try:
            stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    return (
        process.returncode,
        stdout[-MAX_PROCESS_OUTPUT_BYTES:],
        stderr[-MAX_PROCESS_OUTPUT_BYTES:],
    )


def _parse_json_document(raw: str, *, field_name: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_RESULT_JSON_BYTES:
        raise ImageGenerationError(502, "local_tool_invalid_json", f"{field_name}体积过大")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(
            502,
            "local_tool_invalid_json",
            f"{field_name}不是有效 JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise ImageGenerationError(502, "local_tool_invalid_json", f"{field_name}必须是对象")
    return payload


def _capability_from_payload(payload: object) -> ImageGenerationCapability:
    try:
        return ImageGenerationCapability.model_validate(payload)
    except ValidationError as exc:
        raise ImageGenerationError(
            422,
            "local_tool_capability_invalid",
            "本机工具返回了不兼容的能力声明",
        ) from exc


async def detect_local_tool(
    executable_path: str,
    fixed_args: list[str],
    *,
    timeout_seconds: int = 20,
    expected_protocol: str = LOCAL_TOOL_PROTOCOL_VERSION,
    proxy_url: str | None = None,
) -> ToolDetection:
    executable = validate_executable_path(executable_path)
    safe_args = validate_fixed_args(fixed_args)
    started = time.perf_counter()
    return_code, stdout, stderr = await asyncio.to_thread(
        _run_process,
        [str(executable), *safe_args, "capabilities", "--json"],
        cwd=executable.parent,
        timeout_seconds=timeout_seconds,
        proxy_url=proxy_url,
    )
    if return_code != 0:
        message = stderr.strip().splitlines()[-1] if stderr.strip() else "未返回错误说明"
        raise ImageGenerationError(
            422,
            "local_tool_detection_failed",
            f"本机工具检测失败（退出码 {return_code}）：{message[:300]}",
        )
    payload = _parse_json_document(stdout.strip(), field_name="能力检测结果")
    protocol = str(payload.get("protocol_version") or "").strip()
    if protocol != expected_protocol:
        raise ImageGenerationError(
            422,
            "local_tool_protocol_mismatch",
            f"本机工具协议为 {protocol or '未知'}，当前需要 {expected_protocol}",
        )
    tool_id = str(payload.get("tool_id") or "").strip()
    tool_version = str(payload.get("tool_version") or "").strip()
    if not tool_id or not tool_version:
        raise ImageGenerationError(
            422,
            "local_tool_identity_missing",
            "本机工具必须返回 tool_id 和 tool_version",
        )
    return ToolDetection(
        tool_id=tool_id[:120],
        tool_version=tool_version[:120],
        protocol_version=protocol,
        capability=_capability_from_payload(payload.get("capabilities")),
        latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )


async def preflight_codex_local_tool(
    executable_path: str,
    fixed_args: list[str],
    *,
    probe_cwd: Path,
    timeout_seconds: int = 30,
    proxy_url: str | None = None,
) -> CodexSandboxPreflightResult:
    executable = validate_executable_path(executable_path)
    safe_args = validate_fixed_args(fixed_args)
    resolved_cwd = await asyncio.to_thread(probe_cwd.resolve)
    if not await asyncio.to_thread(resolved_cwd.is_dir):
        raise ImageGenerationError(
            422,
            "codex_sandbox_preflight_directory_invalid",
            "Codex 沙箱预检目录不存在",
        )
    started = time.perf_counter()
    return_code, stdout, stderr = await asyncio.to_thread(
        _run_process,
        [
            str(executable),
            *safe_args,
            "preflight",
            "--cwd",
            str(resolved_cwd),
            "--timeout",
            str(timeout_seconds),
        ],
        cwd=executable.parent,
        timeout_seconds=timeout_seconds + 5,
        proxy_url=proxy_url,
    )
    if return_code != 0:
        raw = f"{stderr}\n{stdout}"
        known_error = _codex_windows_sandbox_error(raw)
        if known_error is not None:
            raise known_error
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        detail = lines[-1] if lines else "未返回错误说明"
        raise ImageGenerationError(
            422,
            "codex_sandbox_preflight_failed",
            f"Codex Windows 沙箱预检失败（退出码 {return_code}）：{detail[:700]}",
        )
    payload = _parse_json_document(stdout.strip(), field_name="Codex 沙箱预检结果")
    if payload.get("ready") is not True:
        raise ImageGenerationError(
            422,
            "codex_sandbox_preflight_failed",
            "Codex Windows 沙箱预检没有返回就绪状态",
        )
    return CodexSandboxPreflightResult(
        latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )


def _safe_output_path(output_root: Path, value: object) -> Path:
    raw = str(value or "").strip().replace(chr(92), "/")
    relative = PurePosixPath(raw)
    if (
        not raw
        or not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or ":" in relative.parts[0]
    ):
        raise ImageGenerationError(
            502,
            "local_tool_output_path_invalid",
            "本机工具返回了不安全的候选路径",
        )
    candidate = (output_root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(output_root.resolve())
    except ValueError as exc:
        raise ImageGenerationError(
            502,
            "local_tool_output_path_invalid",
            "本机工具候选路径越界",
        ) from exc
    return candidate


def _validate_image(path: Path, candidate: dict[str, Any]) -> GeneratedImage:
    if not path.is_file():
        raise ImageGenerationError(502, "local_tool_output_missing", "本机工具候选文件不存在")
    size = path.stat().st_size
    if size <= 0 or size > 25 * 1024 * 1024:
        raise ImageGenerationError(502, "local_tool_output_size", "本机工具候选文件体积无效")
    payload = path.read_bytes()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    declared_sha256 = str(candidate.get("sha256") or "").lower()
    if declared_sha256 != actual_sha256:
        raise ImageGenerationError(502, "local_tool_output_hash", "本机工具候选哈希不匹配")
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            image_format = str(source.format or "").upper()
            width, height = image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageGenerationError(
            502,
            "local_tool_output_image",
            "本机工具候选不是有效图片",
        ) from exc
    media_type = SUPPORTED_IMAGE_FORMATS.get(image_format)
    if media_type is None:
        raise ImageGenerationError(502, "local_tool_output_format", "本机工具候选格式不受支持")
    declared_type = str(candidate.get("media_type") or "").lower()
    if declared_type and declared_type != media_type:
        raise ImageGenerationError(502, "local_tool_output_type", "本机工具候选媒体类型不匹配")
    if candidate.get("width") is not None and int(candidate["width"]) != width:
        raise ImageGenerationError(502, "local_tool_output_dimensions", "本机工具候选宽度不匹配")
    if candidate.get("height") is not None and int(candidate["height"]) != height:
        raise ImageGenerationError(502, "local_tool_output_dimensions", "本机工具候选高度不匹配")
    return GeneratedImage(
        payload=payload,
        media_type=media_type,
        width=width,
        height=height,
        metadata={"tool_relative_path": candidate.get("path"), "source_sha256": actual_sha256},
    )


class LocalToolImageAdapter:
    def __init__(
        self,
        *,
        identity: AdapterIdentity,
        executable_path: str,
        fixed_args: list[str],
        timeout_seconds: int,
        proxy_url: str | None = None,
    ) -> None:
        self.identity = identity
        self.executable = validate_executable_path(executable_path)
        self.fixed_args = validate_fixed_args(fixed_args)
        self.timeout_seconds = timeout_seconds
        self.proxy_url = proxy_url

    async def generate(self, request: AdapterRequest) -> AdapterResult:
        filesystem_run_root = _filesystem_path(request.run_root)
        input_root = filesystem_run_root / "tool-inputs"
        output_root = filesystem_run_root / "tool-output"
        input_root.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        inputs: list[dict[str, Any]] = []

        if request.source_path is not None and request.source_sha256 is not None:
            source_name = f"source{request.source_path.suffix.lower() or '.jpg'}"
            source_copy = input_root / source_name
            shutil.copy2(_filesystem_path(request.source_path), source_copy)
            if _sha256_file(source_copy) != request.source_sha256:
                raise ImageGenerationError(409, "source_hash_changed", "原关键帧文件已发生变化")
            inputs.append(
                {
                    "role": "source",
                    "path": f"tool-inputs/{source_name}",
                    "sha256": request.source_sha256,
                }
            )

        for index, reference in enumerate(request.references, start=1):
            suffix = reference.path.suffix.lower() or ".jpg"
            name = f"reference_{index:02d}{suffix}"
            copied = input_root / name
            shutil.copy2(_filesystem_path(reference.path), copied)
            if _sha256_file(copied) != reference.sha256:
                raise ImageGenerationError(409, "reference_hash_changed", "参考资产文件已发生变化")
            inputs.append(
                {
                    "role": reference.role,
                    "asset_id": str(reference.asset_id),
                    "path": f"tool-inputs/{name}",
                    "sha256": reference.sha256,
                    "weight": reference.weight,
                    "crop_hint": reference.crop_hint,
                    "notes": reference.notes,
                }
            )

        request_path = filesystem_run_root / "request.json"
        _write_json(
            request_path,
            {
                "protocol_version": self.identity.protocol_version,
                "request_id": str(request.request_id),
                "input_mode": request.input_mode.value,
                "candidate_count": request.candidate_count,
                "output": {"width": request.width, "height": request.height},
                "prompt": {
                    "positive": request.positive_prompt,
                    "negative": request.negative_prompt,
                },
                "seed": request.seed,
                "inputs": inputs,
            },
        )
        return_code, _stdout, stderr = await asyncio.to_thread(
            _run_process,
            [
                str(self.executable),
                *self.fixed_args,
                "generate",
                "--request",
                str(request_path),
                "--output",
                str(output_root),
            ],
            # Windows CreateProcess rejects an extended-length path as cwd.
            # Request/output paths stay absolute, so a short executable cwd is safe.
            cwd=self.executable.parent,
            timeout_seconds=self.timeout_seconds,
            proxy_url=self.proxy_url,
            cancel_event=request.cancel_event,
        )
        if return_code != 0:
            if self.identity.adapter_id == CODEX_IMAGEGEN_ADAPTER_ID:
                known_error = _codex_windows_sandbox_error(stderr)
                if known_error is not None:
                    raise known_error
            message = stderr.strip().splitlines()[-1] if stderr.strip() else "未返回错误说明"
            raise ImageGenerationError(
                502,
                "local_tool_failed",
                f"本机工具生成失败（退出码 {return_code}）：{message[:500]}",
                retryable=True,
            )

        result_path = output_root / "result.json"
        if not result_path.is_file() or result_path.stat().st_size > MAX_RESULT_JSON_BYTES:
            raise ImageGenerationError(
                502,
                "local_tool_result_missing",
                "本机工具没有返回有效的 result.json",
            )
        result = _parse_json_document(result_path.read_text("utf-8"), field_name="result.json")
        if result.get("status") != "completed":
            raise ImageGenerationError(
                502,
                str(result.get("error_code") or "local_tool_result_failed")[:120],
                str(result.get("error_message") or "本机工具返回失败状态")[:1000],
            )
        if result.get("protocol_version") != self.identity.protocol_version:
            raise ImageGenerationError(
                502,
                "local_tool_result_protocol",
                "本机工具结果协议版本不匹配",
            )
        raw_candidates = result.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ImageGenerationError(502, "local_tool_candidates_missing", "本机工具没有返回候选")
        if len(raw_candidates) > request.candidate_count:
            raise ImageGenerationError(
                502,
                "local_tool_candidates_excess",
                "本机工具返回候选数量超限",
            )
        images = tuple(
            _validate_image(_safe_output_path(output_root, item.get("path")), item)
            for item in raw_candidates
            if isinstance(item, dict)
        )
        if len(images) != len(raw_candidates):
            raise ImageGenerationError(502, "local_tool_candidate_invalid", "本机工具候选格式无效")

        reported_cost = result.get("actual_cost_micros")
        try:
            actual_cost = int(reported_cost) if reported_cost is not None else None
        except (TypeError, ValueError) as exc:
            raise ImageGenerationError(
                502,
                "local_tool_cost_invalid",
                "本机工具返回的成本无效",
            ) from exc
        if actual_cost is not None and actual_cost < 0:
            raise ImageGenerationError(502, "local_tool_cost_invalid", "本机工具返回的成本无效")
        return AdapterResult(
            images=images,
            tool_id=str(result.get("tool_id") or self.identity.model)[:120],
            tool_version=str(result.get("tool_version") or self.identity.model_snapshot)[:120],
            usage=result.get("usage") if isinstance(result.get("usage"), dict) else {},
            actual_cost_micros=actual_cost,
            cost_source=(
                GenerationCostSource.PROVIDER_REPORTED if actual_cost is not None else None
            ),
            output_manifest_path=result_path,
        )
