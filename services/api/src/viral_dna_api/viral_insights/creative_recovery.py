"""Explicit offline repair of ellipsis-rejected ideas, using only a saved response.

Preview is read-only. Applying creates a SQLite backup, then atomically updates
one unchanged failed batch. No model/router/service imports, calls or billing.
"""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from ..models import ModelRun, ModelRunStatus
from .contracts import CreativeIdea, CreativeResultRecovery, ViralConceptSet
from .creative_brief import freeze_brief, validate_brief_checks
from .creative_prompts import IdeaResponse, validate_ideas


def recover_saved_ideas(batch, run):
    if batch.recovery and batch.status == "completed":
        return batch.model_copy(deep=True)
    if (
        batch.status != "failed"
        or batch.error_code != "creative_brief_unmet"
        or batch.phase != "ideas"
        or batch.operation != "generate"
        or batch.ideas
        or batch.concepts
        or batch.published_result
        or batch.recovery
    ):
        raise ValueError("仅支持恢复因旧版引用校验失败的空创意批次，不覆盖已有结果")
    if (
        not batch.model_runs
        or run.id != batch.model_runs[-1]
        or run.analysis_id != batch.analysis_id
        or run.video_id != batch.video_id
        or run.status != ModelRunStatus.COMPLETED
        or run.prompt_version != "creative-ideas-v3"
        or run.schema_version != "creative-content-v3"
    ):
        raise ValueError("模型账本与失败批次不匹配，不能恢复")
    brief = batch.input_snapshot.get("creative_brief")
    if not brief or brief != freeze_brief(batch.feedback):
        raise ValueError("补充想法快照不完整或不一致，不能恢复")
    response = IdeaResponse.model_validate(run.result_payload)
    # Narrow repair: there must actually be an abbreviated quotation that the
    # previous strict substring comparison rejected. Every check must still pass.
    abbreviated = any(
        evidence.scene_index <= len(idea.key_scenes)
        and evidence.quote.strip() not in idea.key_scenes[evidence.scene_index - 1]
        for idea in response.ideas
        for check in idea.brief_checks
        for evidence in check.evidence
    )
    if not abbreviated:
        raise ValueError("未发现旧版省略引用问题，不自动改写此失败批次")
    ideas = [
        CreativeIdea(
            **idea.model_dump(exclude={"brief_checks"}),
            brief_checks=validate_brief_checks(idea, brief, label=f"第 {index} 条创意"),
        )
        for index, idea in enumerate(response.ideas, 1)
    ]
    validate_ideas(ideas)
    response_hash = hashlib.sha256(
        json.dumps(run.result_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    repaired = batch.model_copy(
        deep=True,
        update={
            "status": "completed",
            "ideas": ideas,
            "error_code": None,
            "error_message": None,
            "recovery": CreativeResultRecovery(
                source_model_run_id=run.id,
                source_response_sha256=response_hash,
                previous_error_code=batch.error_code,
                previous_error_message=batch.error_message,
            ),
        },
    )
    return ViralConceptSet.model_validate(repaired.model_dump())


def read_batch_and_run(connection, batch_id):
    row = connection.execute(
        "SELECT payload FROM viral_concept_sets WHERE record_key = ?", (str(batch_id),)
    ).fetchone()
    if not row:
        raise ValueError("指定批次不存在")
    batch = ViralConceptSet.model_validate_json(row[0])
    if batch.id != batch_id or not batch.model_runs:
        raise ValueError("批次标识或模型账本关联无效")
    run_row = connection.execute(
        "SELECT payload FROM model_runs WHERE record_key = ?", (str(batch.model_runs[-1]),)
    ).fetchone()
    if not run_row:
        raise ValueError("原模型结果不存在，不能无模型恢复")
    return batch, ModelRun.model_validate_json(run_row[0]), row[0], run_row[0]


def repair_database(database, batch_id, *, apply=False, backup=None):
    database = Path(database).resolve(strict=True)
    batch_id = UUID(str(batch_id))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        batch, run, original_batch, original_run = read_batch_and_run(source, batch_id)
        recovered = recover_saved_ideas(batch, run)
        result = {
            "preview": not apply,
            "batch_id": str(batch_id),
            "ideas": [idea.name for idea in recovered.ideas],
            "additional_model_calls": 0,
            "model_cost_micros": batch.model_cost_micros,
        }
        if batch.recovery:
            return {**result, "unchanged": True}
        if not apply:
            return result
        if backup is None:
            raise ValueError("应用恢复必须指定新的备份文件路径")
        backup = Path(backup).resolve()
        if backup == database or backup.exists():
            raise ValueError("备份路径必须是新的文件，不覆盖数据库或已有备份")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.touch(exist_ok=False)
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
    # Preserve any unknown historic payload fields as well as the frozen input,
    # original model response, IDs, timestamps and costs.
    updated = json.loads(original_batch)
    restored = recovered.model_dump(mode="json")
    for key in ("status", "ideas", "error_code", "error_message", "recovery"):
        updated[key] = restored[key]
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as target:
        with target:
            target.execute("BEGIN IMMEDIATE")
            _, _, latest_batch, latest_run = read_batch_and_run(target, batch_id)
            if latest_batch != original_batch or latest_run != original_run:
                raise ValueError("批次或模型账本已变化，停止恢复并保留备份")
            running = target.execute(
                "SELECT COUNT(*) FROM viral_concept_sets "
                "WHERE json_extract(payload, '$.analysis_id') = ? "
                "AND json_extract(payload, '$.status') IN ('queued', 'running')",
                (str(batch.analysis_id),),
            ).fetchone()[0]
            if running:
                raise ValueError("当前分析仍有运行中的创意任务，请结束后再恢复")
            cursor = target.execute(
                "UPDATE viral_concept_sets SET payload = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE record_key = ? AND payload = ?",
                (json.dumps(updated, ensure_ascii=False), str(batch_id), original_batch),
            )
            if cursor.rowcount != 1:
                raise ValueError("批次已变化，未写入恢复结果")
    return {**result, "recovered": True, "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--batch", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        result = repair_database(args.database, args.batch, apply=args.apply, backup=args.backup)
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Do not emit Pydantic's raw model input or a traceback to operator logs.
        print(f"恢复未执行或未完成（{type(exc).__name__}），请核对批次、备份路径及任务状态")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
