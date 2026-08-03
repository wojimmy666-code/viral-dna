from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


class RuntimeConfigError(RuntimeError):
    """Raised when the local runtime configuration cannot be persisted safely."""


def local_env_path() -> Path:
    configured = os.getenv("VIRAL_DNA_ENV_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[4]
    if (repository_root / ".env.example").exists():
        return repository_root / ".env.local"
    return Path.cwd().resolve() / ".env.local"


def read_local_env(path: Path | None = None) -> dict[str, str]:
    selected = (path or local_env_path()).resolve()
    if not selected.is_file():
        return {}
    try:
        lines = selected.read_text("utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeConfigError(f"无法读取本地模型配置：{selected}") from exc

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        normalized_key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized_key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[normalized_key] = value
    return values


def get_config_value(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    return read_local_env().get(name, default)


def persist_config_values(
    updates: Mapping[str, str],
    *,
    path: Path | None = None,
) -> Path:
    selected = (path or local_env_path()).resolve()
    normalized: dict[str, str] = {}
    for key, value in updates.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise RuntimeConfigError(f"非法配置项：{key}")
        text = str(value)
        if "\r" in text or "\n" in text:
            raise RuntimeConfigError(f"配置项 {key} 不能包含换行")
        normalized[key] = text

    try:
        existing_lines = selected.read_text("utf-8-sig").splitlines() if selected.is_file() else []
    except OSError as exc:
        raise RuntimeConfigError(f"无法读取本地模型配置：{selected}") from exc

    output_lines: list[str] = []
    written: set[str] = set()
    for line in existing_lines:
        match = ENV_LINE.match(line)
        key = match.group(1) if match else None
        if key not in normalized:
            output_lines.append(line)
            continue
        if key not in written:
            output_lines.append(f"{key}={normalized[key]}")
            written.add(key)

    if output_lines and output_lines[-1] != "":
        output_lines.append("")
    for key, value in normalized.items():
        if key not in written:
            output_lines.append(f"{key}={value}")

    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{selected.name}.",
            suffix=".tmp",
            dir=selected.parent,
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(output_lines).rstrip("\n") + "\n")
        os.replace(temporary_path, selected)
        temporary_path = None
        if os.name != "nt":
            selected.chmod(0o600)
    except OSError as exc:
        raise RuntimeConfigError(f"无法保存本地模型配置：{selected}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    for key, value in normalized.items():
        os.environ[key] = value
    return selected
