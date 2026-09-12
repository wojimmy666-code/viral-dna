"""Incremental, offline supplement. Does not write identity DBs or account workspaces."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .installation_bundle import Settings, disjoint, fail, inventory, json_bytes
from .supplement_data import (
    FORMAT,
    KEY_NAMES,
    MEDIA_NAMES,
    VERSION,
    account_ids,
    canonical_presentation,
    decode,
    digest,
    env_values,
    media_graph,
    merge_env,
    merge_profiles,
    presentation,
    profiles,
    read_bytes,
    read_json,
    uuid_text,
    validated_keys,
    verify_bundle,
)
from .workspace_layout import WorkspaceLayoutError, atomic_bytes, checked_path, io_path, layout_lock

BRIDGE = Path(__file__).resolve().parents[5] / "scripts/maintenance/supplement-crypto.mjs"
EMPTY_PROFILES = {"schema_version": 1, "profiles": []}


def crypto(command, content, unlock, node):
    if not unlock or not node:
        fail("处理模型密钥需要 --unlock-file 和 Node 运行程序")
    unlock = checked_path(unlock)
    if not unlock.name.endswith(".vdna-unlock"):
        fail("解锁文件扩展名必须是 .vdna-unlock")
    if command == "seal-new":
        if unlock.exists():
            fail("解锁文件已存在，不覆盖；请选择新文件名")
        io_path(unlock.parent).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(node), str(BRIDGE), command, str(unlock)],
        input=content,
        capture_output=True,
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        fail("密钥加解密失败：请检查解锁文件、文件完整性与权限；未输出密钥内容")
    return result.stdout


def marker_path(settings):
    # Reuse the existing startup guard, including on servers running older API code.
    return settings.auth.with_suffix(".installation-migration.json")


def root_for(settings):
    root = checked_path(settings.catalog.parent)
    if (
        settings.auth.parent != root
        or settings.accounts.parent != root
        or settings.auth.name != "accounts.sqlite3"
        or settings.catalog.name != "account-catalog.json"
        or settings.accounts.name != "accounts"
        or root == Path(root.anchor)
        or root == Path.home().resolve()
    ):
        fail("身份库、账户目录登记和 accounts 必须在同一专用数据目录")
    return root


def target_path(settings, env_file, name):
    root = root_for(settings)
    if name == "@api.env":
        return checked_path(env_file)
    if name not in {"category-profiles.json", "platform-skills.json"}:
        parts = name.split("/")
        if len(parts) != 3 or parts[0] != "platform-skill-media" or parts[2] not in MEDIA_NAMES:
            fail("补充操作试图修改范围外路径")
        uuid_text(parts[1])
    return checked_path(root / name)


def source_snapshot(settings, env_file, selected_accounts=None, include_keys=False):
    root = settings.catalog.parent
    known = account_ids(settings)
    selected = set(selected_accounts or known)
    if not selected or not selected.issubset(known):
        fail("选择的源账户不存在")
    captured = {}

    def capture(path):
        path = checked_path(path)
        captured[path] = read_bytes(path)
        return captured[path]

    raw = capture(root / "category-profiles.json")
    categories = copy.deepcopy(profiles(decode(raw) if raw is not None else EMPTY_PROFILES))
    categories["profiles"] = [p for p in categories["profiles"] if p["account_id"] in selected]
    raw = capture(root / "platform-skills.json")
    catalog = decode(raw) if raw is not None else {"skills": []}
    displays = []
    for skill in catalog["skills"]:
        value = skill.get("presentation")
        if value and value.get("items"):
            presentation(value)
            displays.append(
                {"skill_id": skill["id"], "presentation": canonical_presentation(value)}
            )
    graph = media_graph(root / "platform-skill-media", displays)
    keys = {}
    if include_keys:
        values = env_values(capture(env_file))
        keys = {name: values[name] for name in sorted(KEY_NAMES) if values.get(name, "").strip()}
        validated_keys({"format": "ViralDNA model keys", "version": 1, "keys": keys})
    return selected, categories, displays, graph, captured, keys


def export_bundle(
    settings,
    env_file,
    bundle,
    *,
    apply=False,
    selected_accounts=None,
    include_keys=False,
    unlock=None,
    node=None,
):
    bundle = checked_path(bundle)
    if not bundle.name.endswith(".vdna-supplement") or bundle.exists():
        fail("请选择尚不存在的 .vdna-supplement 目录")
    root = checked_path(settings.catalog.parent)
    disjoint([root, bundle, checked_path(env_file)])
    if unlock:
        unlock = checked_path(unlock)
        disjoint([root, bundle, checked_path(env_file), unlock])
    selected, categories, displays, graph, captured, keys = source_snapshot(
        settings,
        env_file,
        selected_accounts,
        include_keys,
    )
    report = {
        "preview": not apply,
        "account_ids": sorted(selected),
        "categories": len(categories["profiles"]),
        "skill_presentations": len(displays),
        "media_files": sum(len(files) for files in graph.values()),
        "media_bytes": sum(meta["bytes"] for files in graph.values() for meta in files.values()),
        "model_key_names": sorted(keys),
        "bundle": str(bundle),
        "notes": ["不复制账号密码、会话或项目工作区", "不复制 Skill 定义版本或本机模型授权"],
    }
    if not apply:
        return report
    operation = str(uuid4())
    stage = checked_path(bundle.with_name(bundle.name + ".pending-" + operation))
    io_path(stage).mkdir(parents=True)
    atomic_bytes(stage / "category-profiles.json", json_bytes(categories))
    atomic_bytes(stage / "presentations.json", json_bytes({"items": displays}))
    for identity, files in graph.items():
        destination = stage / "media" / identity
        io_path(destination).mkdir(parents=True)
        for name, meta in files.items():
            source = checked_path(root / "platform-skill-media" / identity / name)
            shutil.copy2(io_path(source), io_path(destination / name))
            if digest(read_bytes(destination / name)) != meta["sha256"]:
                fail("导出时媒体发生变化，未发布补充包")
    if include_keys:
        content = json_bytes(
            {"format": "ViralDNA model keys", "version": 1, "bundle_id": operation, "keys": keys}
        )
        atomic_bytes(stage / "model-keys.vdna-secrets", crypto("seal-new", content, unlock, node))
    if any(read_bytes(path) != before for path, before in captured.items()):
        fail("导出期间配置发生变化，未发布补充包；请使用新的包名重试")
    if media_graph(root / "platform-skill-media", displays) != graph:
        fail("导出期间媒体发生变化，未发布补充包")
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "id": operation,
        "created_at": datetime.now(UTC).isoformat(),
        "account_ids": sorted(selected),
        "files": inventory(stage, hashes=True),
    }
    atomic_bytes(stage / "manifest.json", json_bytes(manifest))
    verify_bundle(stage, allow_pending=True)
    # Only a fully verified directory is published. No preexisting path is replaced.
    if bundle.exists():
        fail("目标目录已出现，不覆盖")
    io_path(stage).rename(io_path(bundle))
    _, _, _, _, checksum = verify_bundle(bundle)
    return {
        **report,
        "exported": True,
        "manifest_sha256": checksum,
        "unlock_file": str(unlock) if include_keys else None,
    }


def plan_import(
    settings,
    env_file,
    bundle,
    *,
    expected_digest=None,
    unlock=None,
    node=None,
    skip_keys=False,
    keep_conflicts=False,
):
    root = root_for(settings)
    env_file = checked_path(env_file)
    bundle = checked_path(bundle)
    disjoint([root, bundle, env_file])
    if unlock:
        disjoint([root, bundle, env_file, checked_path(unlock)])
    if Settings.from_env(env_file, target=True) != settings:
        fail("目标配置路径与本次读取的设置不一致，请重新预览")
    if marker_path(settings).exists():
        fail("发现未完成迁移，请先用本工具 recover 恢复，勿删除标记")
    manifest, categories, displays, _, checksum = verify_bundle(bundle, expected_digest)
    if not set(manifest["account_ids"]).issubset(account_ids(settings)):
        fail("目标账户 ID 不匹配，不按手机号猜测或创建新账户")
    changes, observed, conflicts = {}, {}, []

    def observe(name):
        raw = read_bytes(target_path(settings, env_file, name))
        observed[name] = digest(raw) if raw is not None else None
        return raw

    original_env = observe("@api.env")
    original = observe("category-profiles.json")
    merged, added, problems = merge_profiles(
        decode(original) if original is not None else EMPTY_PROFILES, categories
    )
    conflicts.extend(problems)
    if added:
        changes["category-profiles.json"] = json_bytes(merged)
    catalog_raw = observe("platform-skills.json")
    catalog = decode(catalog_raw) if catalog_raw is not None else {"skills": []}
    if not isinstance(catalog.get("skills"), list):
        fail("正式端 Skill 目录格式不正确")
    skills = {item["id"]: item for item in catalog["skills"]}
    if len(skills) != len(catalog["skills"]):
        fail("正式端 Skill ID 重复")
    updated_skills, kept_skills = [], []
    for display in displays:
        sid, value = display["skill_id"], canonical_presentation(display["presentation"])
        target = skills.get(sid)
        if target is None:
            conflicts.append({"kind": "skill", "id": sid, "reason": "skill_not_installed"})
            continue
        current = target.get("presentation")
        if current:
            presentation(current)
            old = canonical_presentation(current)
            # Revision differs after a successful merge; content equality is idempotent.
            same = {k: v for k, v in old.items() if k != "revision"} == {
                k: v for k, v in value.items() if k != "revision"
            }
            empty_default = not old["items"] and old["revision"] == 0
            if not same and not empty_default:
                conflicts.append({"kind": "skill", "id": sid, "reason": "target_display_differs"})
                continue
        else:
            same = False
        pending = {}
        # Each Skill's complete reachable graph is imported as a unit.
        subset = media_graph(bundle / "media", [display])
        media_conflict = False
        for identity, files in subset.items():
            for name, meta in files.items():
                relative = f"platform-skill-media/{identity}/{name}"
                raw = observe(relative)
                if raw is not None and digest(raw) != meta["sha256"]:
                    media_conflict = True
                elif raw is None:
                    pending[relative] = read_bytes(bundle / "media" / identity / name)
        if media_conflict:
            conflicts.append({"kind": "skill", "id": sid, "reason": "target_media_differs"})
            continue
        changes.update(pending)
        if not same:
            target["presentation"] = copy.deepcopy(value)
            target["presentation"]["revision"] = (current or {}).get("revision", 0) + 1
            updated_skills.append(sid)
        else:
            kept_skills.append(sid)
    if updated_skills:
        changes["platform-skills.json"] = json_bytes(catalog)
    key_actions, keys_skipped = [], False
    encrypted = read_bytes(bundle / "model-keys.vdna-secrets")
    if encrypted is not None:
        if skip_keys:
            keys_skipped = True
        else:
            decrypted = decode(crypto("open", encrypted, unlock, node))
            if decrypted.get("bundle_id") != manifest["id"]:
                fail("模型密钥包与本次补充包不匹配")
            source_keys = validated_keys(decrypted)
            if original_env is None:
                fail("目标 api.env 不存在，不创建空配置")
            target_keys = env_values(original_env)
            updates = {}
            for name, value in source_keys.items():
                current = target_keys.get(name, "").strip()
                if current and current != value:
                    conflicts.append(
                        {"kind": "model_key", "id": name, "reason": "target_key_already_configured"}
                    )
                elif not current:
                    updates[name] = value
                    key_actions.append(name)
            if updates:
                changes["@api.env"] = merge_env(original_env, updates)
    actions = [
        {"target": name, "before": observed[name], "after": digest(content), "bytes": len(content)}
        for name, content in sorted(changes.items())
    ]
    report = {
        "preview": True,
        "bundle_id": manifest["id"],
        "manifest_sha256": checksum,
        "account_ids": manifest["account_ids"],
        "target_data_root": str(root),
        "target_env_file": str(env_file),
        "add_categories": added,
        "update_skill_presentations": updated_skills,
        "unchanged_skill_presentations": kept_skills,
        "add_model_keys": key_actions,
        "model_keys_skipped": keys_skipped,
        "conflicts": conflicts,
        "keep_target_conflicts": keep_conflicts,
        "actions": actions,
        "observed": dict(sorted(observed.items())),
        "ready": not conflicts or keep_conflicts,
    }
    report["plan_sha256"] = digest(json_bytes(report))
    return report, changes


def operation_dir(settings, operation):
    return checked_path(root_for(settings) / "supplement-migrations" / uuid_text(operation))


def journal_for(settings, env_file):
    marker = read_json(marker_path(settings))
    if marker.get("kind") != "supplement" or marker.get("version") != VERSION:
        fail("标记不属于本补充工具，请使用对应迁移工具恢复")
    if marker.get("env_file") != str(checked_path(env_file)):
        fail("恢复必须使用原正式端 api.env 路径")
    operation = operation_dir(settings, marker["operation"])
    journal_raw = read_bytes(operation / "journal.json")
    if journal_raw is None or digest(journal_raw) != marker.get("journal_sha256"):
        fail("恢复日志校验失败，未修改现有数据")
    journal = decode(journal_raw)
    seen = set()
    for item in journal["items"]:
        target_path(settings, env_file, item["target"])
        if item["target"] in seen:
            fail("恢复日志含重复目标")
        seen.add(item["target"])
    return marker, operation, journal


def recover(settings, env_file, *, apply=False, confirm_api_stopped=False, unlock=None, node=None):
    if not marker_path(settings).exists():
        return {"recovery_needed": False}
    with layout_lock(settings.auth, allow_incomplete_import=True):
        marker, operation, journal = journal_for(settings, env_file)
        problems = []
        backups = {}
        for index, item in enumerate(journal["items"]):
            current = read_bytes(target_path(settings, env_file, item["target"]))
            fingerprint = digest(current) if current is not None else None
            if fingerprint not in {item["before"], item["after"]}:
                problems.append(item["target"])
            if item["before"] is not None:
                data = read_bytes(operation / "previous" / str(index))
                if data is None:
                    fail("恢复副本缺失")
                if item["target"] == "@api.env":
                    data = crypto("open", data, unlock, node)
                if digest(data) != item["before"]:
                    fail("恢复副本校验失败")
                backups[item["target"]] = data
        report = {
            "recovery_needed": True,
            "preview": not apply,
            "operation": marker["operation"],
            "conflicts": problems,
            "restore_files": [item["target"] for item in journal["items"]],
        }
        if not apply:
            return report
        if not confirm_api_stopped or problems:
            fail("恢复需确认已停服，且目标不能包含迁移后新增修改")
        for index, item in reversed(list(enumerate(journal["items"]))):
            path = target_path(settings, env_file, item["target"])
            current = read_bytes(path)
            if (digest(current) if current is not None else None) == item["before"]:
                continue
            if (digest(current) if current is not None else None) != item["after"]:
                fail("恢复期间目标发生变化，未覆盖；保持停服并重新检查 recover 预览")
            if item["before"] is not None:
                atomic_bytes(path, backups[item["target"]])
            elif path.exists():
                quarantine = operation / "rolled-back-files"
                io_path(quarantine).mkdir(exist_ok=True)
                io_path(path).rename(io_path(quarantine / str(index)))
        io_path(marker_path(settings)).rename(io_path(operation / "recovered-marker.json"))
        return {**report, "recovered": True, "backup": str(operation)}


def apply_import(
    settings,
    env_file,
    bundle,
    *,
    expected_digest,
    expected_plan,
    confirm_api_stopped=False,
    unlock=None,
    node=None,
    skip_keys=False,
    keep_conflicts=False,
    checkpoint=lambda _: None,
):
    if not confirm_api_stopped or not expected_digest or not expected_plan:
        fail("实际导入需确认已停服，并提供清单及预览摘要")
    failure = None
    with layout_lock(settings.auth):
        report, changes = plan_import(
            settings,
            env_file,
            bundle,
            expected_digest=expected_digest,
            unlock=unlock,
            node=node,
            skip_keys=skip_keys,
            keep_conflicts=keep_conflicts,
        )
        if report["plan_sha256"] != expected_plan:
            fail("预览后源包、目标或选项发生变化，请重新预览")
        if not report["ready"]:
            fail("存在冲突，未修改数据；如需保留正式端冲突项，请重新预览并显式选择保留")
        if not changes:
            return {"imported": True, "changed_files": 0, "idempotent": True}
        root = root_for(settings)
        if shutil.disk_usage(root).free < sum(len(v) for v in changes.values()) * 3 + 33554432:
            fail("目标磁盘空间不足")
        operation_id = str(uuid4())
        operation = operation_dir(settings, operation_id)
        io_path(operation / "previous").mkdir(parents=True)
        items = report["actions"]
        for index, item in enumerate(items):
            raw = read_bytes(target_path(settings, env_file, item["target"]))
            if (digest(raw) if raw is not None else None) != item["before"]:
                fail("目标发生变化，尚未安装任何文件")
            if raw is not None:
                if item["target"] == "@api.env":
                    raw = crypto("seal", raw, unlock, node)
                atomic_bytes(operation / "previous" / str(index), raw)
        journal = json_bytes(
            {
                "items": items,
                "plan_sha256": expected_plan,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        atomic_bytes(operation / "journal.json", journal)
        atomic_bytes(
            marker_path(settings),
            json_bytes(
                {
                    "kind": "supplement",
                    "version": VERSION,
                    "operation": operation_id,
                    "env_file": str(checked_path(env_file)),
                    "journal_sha256": digest(journal),
                }
            ),
        )
        try:
            for item in sorted(
                items,
                key=lambda row: (
                    not row["target"].startswith("platform-skill-media/"),
                    row["target"] == "@api.env",
                    row["target"],
                ),
            ):
                path = target_path(settings, env_file, item["target"])
                raw = read_bytes(path)
                if (digest(raw) if raw is not None else None) != item["before"]:
                    fail("安装期间目标发生变化")
                io_path(path.parent).mkdir(parents=True, exist_ok=True)
                atomic_bytes(path, changes[item["target"]])
                checkpoint(item["target"])
            for item in items:
                if (
                    digest(read_bytes(target_path(settings, env_file, item["target"])))
                    != item["after"]
                ):
                    fail("安装后文件校验失败")
            io_path(marker_path(settings)).rename(io_path(operation / "completed-marker.json"))
            return {
                "imported": True,
                "changed_files": len(items),
                "operation": operation_id,
                "backup": str(operation),
                "added_categories": len(report["add_categories"]),
                "updated_skill_presentations": report["update_skill_presentations"],
                "added_model_keys": report["add_model_keys"],
                "kept_target_conflicts": report["conflicts"],
            }
        except Exception as exc:
            failure = exc
    if failure is not None:
        # Lock must be released before the recovery routine acquires it again.
        try:
            recover(
                settings, env_file, apply=True, confirm_api_stopped=True, unlock=unlock, node=node
            )
        except Exception:
            fail("补充导入中断，自动恢复未完成；保持停服并运行 recover，勿删除标记")
        fail("补充导入失败，已恢复原文件；没有修改账号或项目")


def cli_parser():
    parser = argparse.ArgumentParser(description="增量补齐品类、Skill 展示素材和加密模型密钥")
    parser.add_argument("command", choices=["export", "verify", "import", "recover"])
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--account-id", action="append")
    parser.add_argument("--include-model-keys", action="store_true")
    parser.add_argument("--unlock-file", type=Path)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--skip-model-keys", action="store_true")
    parser.add_argument("--keep-target-conflicts", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-api-stopped", action="store_true")
    parser.add_argument("--save-report", type=Path)
    return parser


def main(argv=None):
    args = cli_parser().parse_args(argv)
    try:
        if args.command == "verify":
            *_, checksum = verify_bundle(args.bundle, args.manifest_sha256)
            result = {"verified": True, "manifest_sha256": checksum}
        else:
            if not args.env_file:
                fail("需要 --env-file")
            settings = Settings.from_env(args.env_file, target=args.command != "export")
            if args.command == "export":
                result = export_bundle(
                    settings,
                    args.env_file,
                    args.bundle,
                    apply=args.apply,
                    selected_accounts=args.account_id,
                    include_keys=args.include_model_keys,
                    unlock=args.unlock_file,
                    node=args.node,
                )
            elif args.command == "recover":
                result = recover(
                    settings,
                    args.env_file,
                    apply=args.apply,
                    confirm_api_stopped=args.confirm_api_stopped,
                    unlock=args.unlock_file,
                    node=args.node,
                )
            else:
                options = {
                    "expected_digest": args.manifest_sha256,
                    "unlock": args.unlock_file,
                    "node": args.node,
                    "skip_keys": args.skip_model_keys,
                    "keep_conflicts": args.keep_target_conflicts,
                }
                if args.apply:
                    result = apply_import(
                        settings,
                        args.env_file,
                        args.bundle,
                        expected_plan=args.plan_sha256,
                        confirm_api_stopped=args.confirm_api_stopped,
                        **options,
                    )
                else:
                    result, _ = plan_import(settings, args.env_file, args.bundle, **options)
        if args.save_report:
            # Never allow a report argument to overwrite configuration or user files.
            report_path = checked_path(args.save_report)
            with io_path(report_path).open("xb") as output:
                output.write(json_bytes(result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("操作已中断；若导入已开始，请保持停服并先用 recover 预览恢复。", file=sys.stderr)
        return 130
    except Exception as error:
        # CLI failures must not echo parse errors containing secret configuration values.
        message = str(error) if isinstance(error, WorkspaceLayoutError) else "配置或文件校验失败"
        print(f"补充迁移未完成：{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
