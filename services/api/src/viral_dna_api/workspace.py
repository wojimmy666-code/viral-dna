from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from .models import WorkspaceValidationResponse
from .runtime_config import RuntimeConfigError, get_config_value, persist_config_values

WORKSPACE_SCHEMA_VERSION = 1


class WorkspaceError(RuntimeError):
    """Raised when a workspace path cannot be validated or initialized safely."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path
    metadata_dir: Path
    database: Path
    records: Path
    temporary: Path


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class WorkspaceManager:
    """Owns the active local workspace and all workspace-relative path rules."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        configured = get_config_value(
            "VIRAL_DNA_WORKSPACE_ROOT",
            get_config_value("VIRAL_DNA_STORAGE_ROOT", "storage"),
        )
        root = self.normalize(configured)
        self._paths = self.initialize(root)

    @staticmethod
    def normalize(raw_path: str | Path) -> Path:
        text = str(raw_path).strip()
        if not text:
            raise WorkspaceError("工作区路径不能为空")
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            return candidate.resolve()
        except OSError as exc:
            raise WorkspaceError("无法解析工作区路径") from exc

    @staticmethod
    def paths_for(root: Path) -> WorkspacePaths:
        normalized = root.resolve()
        metadata_dir = normalized / ".viraldna"
        return WorkspacePaths(
            root=normalized,
            metadata_dir=metadata_dir,
            database=metadata_dir / "workspace.db",
            records=normalized / "records",
            temporary=normalized / "temp",
        )

    @property
    def paths(self) -> WorkspacePaths:
        # Tests use an in-memory repository and frequently isolate media files by
        # changing the legacy storage environment variable after module import.
        if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
            dynamic = os.getenv("VIRAL_DNA_WORKSPACE_ROOT", "").strip() or os.getenv(
                "VIRAL_DNA_STORAGE_ROOT", ""
            ).strip()
            if dynamic:
                return self.paths_for(self.normalize(dynamic))
        with self._lock:
            return self._paths

    @property
    def root(self) -> Path:
        return self.paths.root

    @property
    def database_path(self) -> Path:
        return self.paths.database

    def validate(self, raw_path: str | Path) -> WorkspaceValidationResponse:
        try:
            candidate = self.normalize(raw_path)
        except WorkspaceError as exc:
            return WorkspaceValidationResponse(
                valid=False,
                normalized_path=str(raw_path),
                exists=False,
                writable=False,
                error=str(exc),
            )

        exists = candidate.exists()
        if exists and not candidate.is_dir():
            return WorkspaceValidationResponse(
                valid=False,
                normalized_path=str(candidate),
                exists=True,
                writable=False,
                error="工作区路径必须是文件夹",
            )

        probe_parent = candidate
        while not probe_parent.exists() and probe_parent != probe_parent.parent:
            probe_parent = probe_parent.parent
        if not probe_parent.is_dir():
            return WorkspaceValidationResponse(
                valid=False,
                normalized_path=str(candidate),
                exists=exists,
                writable=False,
                error="找不到可用的工作区父目录",
            )

        probe = probe_parent / f".viraldna-write-test-{uuid4().hex}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            probe.unlink(missing_ok=True)
            return WorkspaceValidationResponse(
                valid=False,
                normalized_path=str(candidate),
                exists=exists,
                writable=False,
                error="该目录不可写，请选择拥有写入权限的位置",
            )

        return WorkspaceValidationResponse(
            valid=True,
            normalized_path=str(candidate),
            exists=exists,
            writable=True,
        )

    def initialize(self, root: Path) -> WorkspacePaths:
        validation = self.validate(root)
        if not validation.valid:
            raise WorkspaceError(validation.error or "工作区不可用")
        paths = self.paths_for(Path(validation.normalized_path))
        try:
            paths.root.mkdir(parents=True, exist_ok=True)
            paths.metadata_dir.mkdir(parents=True, exist_ok=True)
            paths.records.mkdir(parents=True, exist_ok=True)
            paths.temporary.mkdir(parents=True, exist_ok=True)
            self._migrate_legacy_database(paths)
            self._write_metadata(paths)
        except OSError as exc:
            raise WorkspaceError(f"无法初始化工作区：{exc}") from exc
        return paths

    def activate(self, raw_path: str | Path, *, persist: bool = True) -> WorkspacePaths:
        candidate = self.normalize(raw_path)
        prepared = self.initialize(candidate)
        if persist:
            try:
                persist_config_values(
                    {
                        "VIRAL_DNA_WORKSPACE_ROOT": str(prepared.root),
                    }
                )
            except RuntimeConfigError as exc:
                raise WorkspaceError(str(exc)) from exc
        with self._lock:
            self._paths = prepared
        return prepared

    def relative(self, path: Path) -> str:
        candidate = path.resolve()
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("文件不在当前工作区内") from exc
        return relative.as_posix()

    def resolve(self, relative_path: str) -> Path:
        candidate_path = Path(relative_path)
        if candidate_path.is_absolute():
            raise WorkspaceError("工作区文件路径必须是相对路径")
        candidate = (self.root / candidate_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("工作区文件路径越界") from exc
        return candidate

    def record_root(self, record_id: UUID) -> Path:
        return self.paths.records / str(record_id)

    def source_root(self, record_id: UUID) -> Path:
        return self.record_root(record_id) / "source"

    def analysis_root(self, record_id: UUID, analysis_id: UUID) -> Path:
        return self.record_root(record_id) / "analyses" / str(analysis_id)

    def export_root(self, record_id: UUID, analysis_id: UUID) -> Path:
        return self.record_root(record_id) / "exports" / str(analysis_id)

    @staticmethod
    def _migrate_legacy_database(paths: WorkspacePaths) -> None:
        if paths.database.exists():
            return
        legacy = paths.root / "viral_dna.db"
        if not legacy.is_file():
            return
        source = sqlite3.connect(legacy)
        destination = sqlite3.connect(paths.database)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    @staticmethod
    def _write_metadata(paths: WorkspacePaths) -> None:
        metadata_path = paths.metadata_dir / "workspace.json"
        created_at = _utc_iso()
        if metadata_path.is_file():
            try:
                existing = json.loads(metadata_path.read_text("utf-8-sig"))
                created_at = str(existing.get("created_at") or created_at)
            except (OSError, ValueError, TypeError):
                pass
        payload = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "created_at": created_at,
            "updated_at": _utc_iso(),
        }
        temporary = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, metadata_path)
        finally:
            temporary.unlink(missing_ok=True)


workspace_manager = WorkspaceManager()
