"""Prepare a short-path ZIP plus a separately protected model-key unlock file."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/src"))

from viral_dna_api.accounts.installation_bundle import (
    Settings,
    disjoint,
    inventory,
    json_bytes,
)
from viral_dna_api.accounts.supplement_data import digest, verify_bundle
from viral_dna_api.accounts.supplement_transfer import export_bundle
from viral_dna_api.accounts.workspace_layout import (
    WorkspaceLayoutError,
    atomic_bytes,
    checked_path,
    io_path,
)

TOOLS = (
    "scripts/maintenance/transfer-supplement.py",
    "scripts/maintenance/supplement-menu.py",
    "scripts/maintenance/supplement-crypto.mjs",
    "services/api/src/viral_dna_api/__init__.py",
    "services/api/src/viral_dna_api/runtime_config.py",
    "services/api/src/viral_dna_api/schema.py",
    "services/api/src/viral_dna_api/accounts/__init__.py",
    "services/api/src/viral_dna_api/accounts/workspace_layout.py",
    "services/api/src/viral_dna_api/accounts/installation_bundle.py",
    "services/api/src/viral_dna_api/accounts/supplement_data.py",
    "services/api/src/viral_dna_api/accounts/supplement_transfer.py",
)


def build(
    settings,
    env_file,
    output,
    *,
    apply=False,
    include_keys=False,
    unlock=None,
    node=None,
):
    output = checked_path(output)
    archive = checked_path(output.with_name(output.name + ".zip"))
    if (
        not output.name.endswith(".vdna-supplement-kit")
        or output.exists()
        or archive.exists()
    ):
        raise WorkspaceLayoutError(
            "请选择尚不存在的 .vdna-supplement-kit 目录及同名 ZIP"
        )
    paths = [
        output,
        archive,
        checked_path(settings.catalog.parent),
        checked_path(env_file),
    ]
    if unlock:
        paths.append(checked_path(unlock))
    disjoint(paths)
    preview = export_bundle(
        settings,
        env_file,
        output / "payload.vdna-supplement",
        include_keys=include_keys,
        unlock=unlock,
        node=node,
    )
    if not apply:
        return {**preview, "kit": str(output), "zip": str(archive)}
    stage = checked_path(output.with_name(output.name + ".pending-" + str(uuid4())))
    io_path(stage).mkdir(parents=True)
    # These support modules use only the Python standard library; API dependencies are absent.
    for name in TOOLS:
        source, target = checked_path(ROOT / name), stage / name
        io_path(target.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(io_path(source), io_path(target))
    template = ROOT / "scripts/maintenance/templates/supplement"
    for name in ("README.md", "migrate.bat"):
        raw = (template / name).read_bytes()
        if name.endswith(".bat"):
            raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        atomic_bytes(stage / name, raw)
    exported = export_bundle(
        settings,
        env_file,
        stage / "payload.vdna-supplement",
        apply=True,
        include_keys=include_keys,
        unlock=unlock,
        node=node,
    )
    spec = {
        "format": "ViralDNA supplement kit",
        "version": 1,
        "manifest_sha256": exported["manifest_sha256"],
        "unlock_file_name": Path(unlock).name if include_keys else None,
        "files": inventory(stage, hashes=True),
    }
    atomic_bytes(stage / "kit.json", json_bytes(spec))
    actual = inventory(stage, hashes=True)
    if any(name.endswith((".vdna-unlock", ".env", ".sqlite3")) for name in actual):
        raise WorkspaceLayoutError("工具包包含禁止打包的文件，未发布")
    verify_bundle(stage / "payload.vdna-supplement", exported["manifest_sha256"])
    if output.exists() or archive.exists():
        raise WorkspaceLayoutError("输出路径已经出现，不覆盖")
    io_path(stage).rename(io_path(output))
    pending_zip = checked_path(
        archive.with_name(archive.name + ".pending-" + str(uuid4()))
    )
    with zipfile.ZipFile(
        io_path(pending_zip), "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for name in sorted(actual):
            zf.write(io_path(output / name), arcname=f"{output.name}/{name}")
    with zipfile.ZipFile(io_path(pending_zip)) as zf:
        if zf.testzip() is not None:
            raise WorkspaceLayoutError("ZIP 校验失败，未发布压缩包")
        for name, meta in actual.items():
            if digest(zf.read(f"{output.name}/{name}")) != meta["sha256"]:
                raise WorkspaceLayoutError("ZIP 内文件与原文件不一致，未发布")
    io_path(pending_zip).rename(io_path(archive))
    return {
        **exported,
        "bundle": str(output / "payload.vdna-supplement"),
        "kit": str(output),
        "zip": str(archive),
        "zip_bytes": archive.stat().st_size,
        "zip_sha256": digest(archive.read_bytes()),
        "zip_files": len(actual),
        "zip_verified": True,
        "unlock_file": str(unlock) if include_keys else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="生成独立补充迁移菜单包；解锁文件必须单独保管"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-model-keys", action="store_true")
    parser.add_argument("--unlock-file", type=Path)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(args.env_file)
        result = build(
            settings,
            args.env_file,
            args.output,
            apply=args.apply,
            include_keys=args.include_model_keys,
            unlock=args.unlock_file,
            node=args.node,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001 - secret-bearing input errors must be redacted
        message = (
            str(error)
            if isinstance(error, WorkspaceLayoutError)
            else "配置或文件检查失败"
        )
        print(f"补充包未完成：{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
