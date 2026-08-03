from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from .chinese import simplify_model
from .models import (
    AnalysisRecord,
    AnalysisReport,
    ExportArtifact,
    ExportKind,
)
from .workspace import WorkspaceError, workspace_manager


class ExportRepository(Protocol):
    async def save_export(self, artifact: ExportArtifact) -> ExportArtifact: ...


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timestamp(seconds: float, *, srt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _markdown(report: AnalysisReport) -> str:
    lines = [
        "# ViralDNA 视频拆解报告",
        "",
        f"- 分析版本：`{report.analysis_id}`",
        f"- 视频时长：{report.overview.duration_seconds:.2f} 秒",
        f"- 画面比例：{report.overview.aspect_ratio}",
        f"- 爆点潜力：{report.overview.viral_potential_score}/100",
        "",
        "## 视频概览",
        "",
        report.overview.summary,
        "",
        "## 分镜拆解",
        "",
    ]
    for shot in report.shots:
        lines.extend(
            [
                f"### {shot.index}. {shot.title}",
                "",
                f"- 时间：{_timestamp(shot.start_seconds)} → {_timestamp(shot.end_seconds)}",
                f"- 主体：{'、'.join(shot.subjects) if shot.subjects else '未识别'}",
                f"- 动作：{shot.action}",
                f"- 场景：{shot.scene}",
                f"- 镜头：{shot.camera}",
                f"- 构图：{shot.composition}",
                f"- 灯光：{shot.lighting}",
                f"- 色彩：{shot.color}",
                f"- 对白：{shot.dialogue or '无'}",
                f"- 字幕：{shot.subtitle_text or '无'}",
                "",
                "复刻提示词：",
                "",
                shot.prompt,
                "",
            ]
        )
    lines.extend(["## 爆点分析", ""])
    if report.viral_findings:
        for finding in report.viral_findings:
            lines.extend(
                [
                    f"### {finding.title}（{finding.score}/100）",
                    "",
                    finding.observation,
                    "",
                    f"机制：{finding.mechanism}",
                    "",
                    f"建议：{finding.recommendation}",
                    "",
                ]
            )
    else:
        lines.extend(["当前分析版本尚未生成爆点推理。", ""])
    return "\n".join(lines).rstrip() + "\n"


def _transcript(report: AnalysisReport) -> str:
    timeline = report.evidence_timeline
    if timeline and timeline.transcript_segments:
        return "\n".join(
            f"[{_timestamp(item.start_seconds)} - {_timestamp(item.end_seconds)}] {item.text}"
            for item in timeline.transcript_segments
        ) + "\n"
    dialogue = [
        f"[{_timestamp(shot.start_seconds)} - {_timestamp(shot.end_seconds)}] {shot.dialogue}"
        for shot in report.shots
        if shot.dialogue
    ]
    return ("\n".join(dialogue) + "\n") if dialogue else "未识别到语音对白。\n"


def _subtitle_rows(report: AnalysisReport) -> Iterable[tuple[float, float, str]]:
    timeline = report.evidence_timeline
    if timeline and timeline.subtitle_cues:
        return (
            (item.start_seconds, item.end_seconds, item.text)
            for item in timeline.subtitle_cues
        )
    if timeline and timeline.transcript_segments:
        return (
            (item.start_seconds, item.end_seconds, item.text)
            for item in timeline.transcript_segments
        )
    return (
        (shot.start_seconds, shot.end_seconds, shot.subtitle_text or shot.dialogue or "")
        for shot in report.shots
        if shot.subtitle_text or shot.dialogue
    )


def _subtitles(report: AnalysisReport) -> str:
    blocks = []
    for index, (start, end, text) in enumerate(_subtitle_rows(report), start=1):
        blocks.append(
            f"{index}\n{_timestamp(start, srt=True)} --> {_timestamp(end, srt=True)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


class ExportService:
    def __init__(self, repository: ExportRepository) -> None:
        self.repository = repository

    async def create(
        self,
        record: AnalysisRecord,
        report: AnalysisReport,
        kinds: list[ExportKind],
        *,
        filename_suffix: str = "",
    ) -> list[ExportArtifact]:
        simplified = simplify_model(report)
        root = workspace_manager.export_root(record.id, report.analysis_id)
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        artifacts: list[ExportArtifact] = []
        for kind in kinds:
            filename, media_type, content = self._render(kind, simplified)
            if filename_suffix:
                path = Path(filename)
                filename = f"{path.stem}{filename_suffix}{path.suffix}"
            payload = content.encode("utf-8")
            destination = root / filename
            await asyncio.to_thread(self._write_atomic, destination, payload)
            artifact = ExportArtifact(
                record_id=record.id,
                analysis_id=report.analysis_id,
                kind=kind,
                filename=filename,
                relative_path=workspace_manager.relative(destination),
                media_type=media_type,
                size_bytes=len(payload),
                sha256=_sha256(payload),
            )
            artifacts.append(await self.repository.save_export(artifact))
        return artifacts

    @staticmethod
    def resolve(artifact: ExportArtifact) -> Path:
        candidate = workspace_manager.resolve(artifact.relative_path)
        if not candidate.is_file():
            raise WorkspaceError("导出文件不存在")
        return candidate

    @staticmethod
    def _render(kind: ExportKind, report: AnalysisReport) -> tuple[str, str, str]:
        if kind == ExportKind.REPORT_JSON:
            return "report.json", "application/json", report.model_dump_json(indent=2) + "\n"
        if kind == ExportKind.REPORT_MARKDOWN:
            return "report.md", "text/markdown; charset=utf-8", _markdown(report)
        if kind == ExportKind.PROMPT_PACKAGE:
            content = json.dumps(
                report.prompt_package.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            return "prompt-package.json", "application/json", content + "\n"
        if kind == ExportKind.TRANSCRIPT:
            return "transcript.txt", "text/plain; charset=utf-8", _transcript(report)
        if kind == ExportKind.SUBTITLES:
            return "subtitles.srt", "application/x-subrip; charset=utf-8", _subtitles(report)
        raise ValueError(f"不支持的导出类型：{kind}")

    @staticmethod
    def _write_atomic(destination: Path, payload: bytes) -> None:
        temporary = destination.with_name(f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


async def archive_report(record_id: UUID, report: AnalysisReport) -> Path:
    simplified = simplify_model(report)
    destination = workspace_manager.analysis_root(record_id, report.analysis_id) / "report.json"
    await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
    payload = (simplified.model_dump_json(indent=2) + "\n").encode("utf-8")
    await asyncio.to_thread(ExportService._write_atomic, destination, payload)
    return destination
