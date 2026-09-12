from __future__ import annotations

import copy
import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.accounts.installation_bundle import Settings, inventory, json_bytes
from viral_dna_api.accounts.supplement_data import digest, env_values
from viral_dna_api.accounts.supplement_transfer import (
    apply_import,
    crypto,
    export_bundle,
    main,
    marker_path,
    plan_import,
    recover,
)
from viral_dna_api.accounts.workspace_layout import WorkspaceLayoutError, layout_lock

NODE = shutil.which("node")
AID = "f990a429-061d-49f6-ac49-ff55f7bbc13e"
OTHER = "57f1f137-9772-46c9-9a75-3a5322a7ba9c"
SID = "platform.cinematic-product-story"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def profile(name="测试品类", aid=AID):
    return {
        "id": str(uuid4()),
        "account_id": aid,
        "display_name": name,
        "category_name": "产品",
        "brief": "仅测试",
        "audiences": ["测试人群"],
        "selling_points": ["测试卖点"],
        "revision": 1,
        "usage_count": 0,
        "created_at": "2026-09-12T00:00:00Z",
        "updated_at": "2026-09-12T00:00:00Z",
    }


def empty_display():
    return {
        "schema_version": "viraldna.skill-presentation/v1",
        "revision": 0,
        "primary_item_id": None,
        "items": [],
    }


def installation(base, *, target=False):
    data = base / "data"
    data.mkdir(parents=True)
    auth = data / "accounts.sqlite3"
    with sqlite3.connect(auth) as db:
        db.execute("CREATE TABLE auth_accounts(id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO auth_accounts VALUES (?)", (AID,))
        db.execute("CREATE TABLE auth_users(id TEXT, username TEXT, password_hash TEXT)")
        db.execute(
            "INSERT INTO auth_users VALUES ('user', ?, 'keep-password-hash')",
            ("13817797814" if target else "13917797814",),
        )
    settings = Settings(auth, data / "account-catalog.json", data / "accounts")
    save(settings.catalog, {"preserve": "account-and-workspace-identities"})
    project = settings.accounts / AID / "projects" / "must-stay.txt"
    project.parent.mkdir(parents=True)
    project.write_text("existing production project", encoding="utf-8")
    env = base / "config" / "api.env"
    env.parent.mkdir()
    env.write_text(
        f"VIRAL_DNA_AUTH_MODE=password\nVIRAL_DNA_AUTH_DB_PATH={auth}\n"
        f"VIRAL_DNA_ACCOUNT_CATALOG_PATH={settings.catalog}\n"
        f"VIRAL_DNA_ACCOUNTS_ROOT={settings.accounts}\n"
        "VIRAL_DNA_CORS_ORIGINS=https://production.invalid\n"
        "UNRELATED=preserve-exactly\nDASHSCOPE_API_KEY=\n",
        encoding="utf-8",
    )
    save(
        data / "platform-skills.json",
        {
            "schema_version": 1,
            "skills": [{"id": SID, "name": "保留正式名称", "presentation": empty_display()}],
            "versions": [{"id": "keep-existing-skill-version", "custom": True}],
        },
    )
    return settings, env


@pytest.fixture
def context(tmp_path):
    source, source_env = installation(tmp_path / "source")
    target, target_env = installation(tmp_path / "target", target=True)
    category = profile()
    save(
        source.catalog.parent / "category-profiles.json",
        {"schema_version": 1, "profiles": [category]},
    )
    asset_id, item_id, poster_id = str(uuid4()), str(uuid4()), str(uuid4())
    display = {
        **empty_display(),
        "revision": 7,
        "primary_item_id": item_id,
        "items": [
            {
                "id": item_id,
                "video_asset_id": asset_id,
                "poster_asset_id": poster_id,
                "sort_order": 0,
            }
        ],
    }
    catalog = json.loads((source.catalog.parent / "platform-skills.json").read_text("utf-8"))
    catalog["skills"][0]["presentation"] = display
    save(source.catalog.parent / "platform-skills.json", catalog)
    media = source.catalog.parent / "platform-skill-media" / asset_id
    payload = b"fixture video original"
    save(
        media / "asset.json",
        {
            "id": asset_id,
            "skill_id": SID,
            "status": "ready",
            "kind": "video",
            "source_size": len(payload),
            "source_sha256": digest(payload),
            "original_filename": "fixture.mp4",
            "poster_asset_id": poster_id,
            "created_at": "2026-09-12T00:00:00Z",
            "updated_at": "2026-09-12T00:00:00Z",
        },
    )
    (media / "source.bin").write_bytes(payload)
    (media / "preview.mp4").write_bytes(b"fixture preview")
    (media / "first-frame.jpg").write_bytes(b"fixture frame")
    poster = source.catalog.parent / "platform-skill-media" / poster_id
    save(
        poster / "asset.json",
        {
            "id": poster_id,
            "skill_id": SID,
            "status": "ready",
            "kind": "image",
            "source_size": 0,
            "original_filename": "fixture poster",
            "parent_asset_id": asset_id,
            "created_at": "2026-09-12T00:00:00Z",
            "updated_at": "2026-09-12T00:00:00Z",
        },
    )
    (poster / "preview.webp").write_bytes(b"fixture poster")
    with source_env.open("a", encoding="utf-8") as stream:
        stream.write("DASHSCOPE_API_KEY=fixture-source-secret\nARK_API_KEY=fixture-ark-secret\n")
    return SimpleNamespace(
        source=source,
        source_env=source_env,
        target=target,
        target_env=target_env,
        category=category,
        asset_id=asset_id,
        bundle=tmp_path / "bundle.vdna-supplement",
        unlock=tmp_path / "private" / "model.vdna-unlock",
    )


def exported(ctx, keys=False):
    if keys and not NODE:
        pytest.skip("Node is required for encrypted secret transfer")
    report = export_bundle(
        ctx.source,
        ctx.source_env,
        ctx.bundle,
        apply=True,
        include_keys=keys,
        unlock=ctx.unlock if keys else None,
        node=NODE,
    )
    return report["manifest_sha256"]


def planned(ctx, checksum, **kwargs):
    return plan_import(
        ctx.target,
        ctx.target_env,
        ctx.bundle,
        expected_digest=checksum,
        unlock=ctx.unlock,
        node=NODE,
        **kwargs,
    )[0]


def apply(ctx, plan, **kwargs):
    return apply_import(
        ctx.target,
        ctx.target_env,
        ctx.bundle,
        expected_digest=plan["manifest_sha256"],
        expected_plan=plan["plan_sha256"],
        confirm_api_stopped=True,
        unlock=ctx.unlock,
        node=NODE,
        **kwargs,
    )


def refresh_manifest(bundle):
    value = json.loads((bundle / "manifest.json").read_text("utf-8"))
    entries = inventory(bundle, hashes=True)
    entries.pop("manifest.json", None)
    value["files"] = entries
    save(bundle / "manifest.json", value)
    return digest((bundle / "manifest.json").read_bytes())


def test_export_and_preview_do_not_modify_existing_data(context):
    ctx = context
    before = inventory(ctx.source.catalog.parent, hashes=True)
    report = export_bundle(ctx.source, ctx.source_env, ctx.bundle)
    assert report["preview"] and not ctx.bundle.exists()
    checksum = exported(ctx)
    target_before = inventory(ctx.target.catalog.parent, hashes=True)
    plan = planned(ctx, checksum)
    assert plan["ready"] and len(plan["add_categories"]) == 1
    assert inventory(ctx.source.catalog.parent, hashes=True) == before
    assert inventory(ctx.target.catalog.parent, hashes=True) == target_before
    assert not (ctx.bundle / "identity").exists()


def test_import_preserves_phone_password_projects_other_profiles_and_skill_versions(context):
    ctx = context
    extra = profile("正式端新增")
    save(
        ctx.target.catalog.parent / "category-profiles.json",
        {"schema_version": 1, "profiles": [extra]},
    )
    auth = ctx.target.auth.read_bytes()
    catalog = ctx.target.catalog.read_bytes()
    projects = inventory(ctx.target.accounts, hashes=True)
    checksum = exported(ctx, keys=True)
    plan = planned(ctx, checksum)
    assert "fixture-source-secret" not in json.dumps(plan)
    result = apply(ctx, plan)
    assert result["added_categories"] == 1
    assert result["added_model_keys"] == ["ARK_API_KEY", "DASHSCOPE_API_KEY"]
    assert ctx.target.auth.read_bytes() == auth
    assert ctx.target.catalog.read_bytes() == catalog
    assert inventory(ctx.target.accounts, hashes=True) == projects
    state = json.loads((ctx.target.catalog.parent / "platform-skills.json").read_text("utf-8"))
    assert state["versions"] == [{"id": "keep-existing-skill-version", "custom": True}]
    assert state["skills"][0]["name"] == "保留正式名称"
    env = ctx.target_env.read_text("utf-8")
    assert "UNRELATED=preserve-exactly" in env and "https://production.invalid" in env
    assert "DASHSCOPE_API_KEY=fixture-source-secret" in env
    assert b"fixture-source-secret" not in (ctx.bundle / "model-keys.vdna-secrets").read_bytes()
    assert not marker_path(ctx.target).exists()
    repeat = planned(ctx, checksum)
    assert not repeat["actions"]
    assert apply(ctx, repeat)["idempotent"]


@pytest.mark.parametrize("kind", ["category-id", "category-name", "skill", "media", "key"])
def test_conflicts_block_or_explicitly_keep_target(context, kind):
    ctx = context
    checksum = exported(ctx, keys=kind == "key")
    if kind.startswith("category"):
        other = copy.deepcopy(ctx.category)
        other["brief"] = "正式端修改"
        if kind == "category-name":
            other["id"] = str(uuid4())
        save(
            ctx.target.catalog.parent / "category-profiles.json",
            {"schema_version": 1, "profiles": [other]},
        )
    elif kind == "skill":
        path = ctx.target.catalog.parent / "platform-skills.json"
        state = json.loads(path.read_text("utf-8"))
        state["skills"][0]["presentation"]["revision"] = 2  # deliberate target clear
        save(path, state)
    elif kind == "media":
        path = ctx.target.catalog.parent / "platform-skill-media" / ctx.asset_id / "preview.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"target must not be replaced")
    else:
        with ctx.target_env.open("a", encoding="utf-8") as stream:
            stream.write("DASHSCOPE_API_KEY=fixture-production-secret\n")
    plan = planned(ctx, checksum)
    assert not plan["ready"] and plan["conflicts"]
    with pytest.raises(WorkspaceLayoutError, match="冲突"):
        apply(ctx, plan)
    keep = planned(ctx, checksum, keep_conflicts=True)
    result = apply(ctx, keep, keep_conflicts=True)
    assert result.get("kept_target_conflicts")
    if kind == "key":
        assert "fixture-production-secret" in ctx.target_env.read_text("utf-8")


def test_stale_preview_and_unknown_accounts_fail(context):
    ctx = context
    checksum = exported(ctx)
    plan = planned(ctx, checksum)
    save(
        ctx.target.catalog.parent / "category-profiles.json",
        {"schema_version": 1, "profiles": [profile("新增")]},
    )
    with pytest.raises(WorkspaceLayoutError, match="重新预览"):
        apply(ctx, plan)
    with sqlite3.connect(ctx.target.auth) as db:
        db.execute("UPDATE auth_accounts SET id=?", (OTHER,))
    with pytest.raises(WorkspaceLayoutError, match="账户 ID"):
        planned(ctx, checksum)


def test_exception_rolls_back_and_uses_encrypted_env_backup(context):
    ctx = context
    checksum = exported(ctx, keys=True)
    original_env = ctx.target_env.read_bytes()
    original_catalog = (ctx.target.catalog.parent / "platform-skills.json").read_bytes()

    def checkpoint(name):
        if name == "@api.env":
            raise RuntimeError("fixture failure")

    with pytest.raises(WorkspaceLayoutError, match="已恢复"):
        apply(ctx, planned(ctx, checksum), checkpoint=checkpoint)
    assert ctx.target_env.read_bytes() == original_env
    assert (ctx.target.catalog.parent / "platform-skills.json").read_bytes() == original_catalog
    assert not (ctx.target.catalog.parent / "category-profiles.json").exists()
    assert not marker_path(ctx.target).exists()
    assert list(
        (ctx.target.catalog.parent / "supplement-migrations").rglob("recovered-marker.json")
    )
    folder = next((ctx.target.catalog.parent / "supplement-migrations").iterdir())
    journal = json.loads((folder / "journal.json").read_text("utf-8"))
    index = next(i for i, row in enumerate(journal["items"]) if row["target"] == "@api.env")
    encrypted_backup = (folder / "previous" / str(index)).read_bytes()
    assert b"UNRELATED=preserve-exactly" not in encrypted_backup
    assert crypto("open", encrypted_backup, ctx.unlock, NODE) == original_env


def test_crash_guard_recover_and_no_overwrite_after_manual_edit(context):
    ctx = context
    checksum = exported(ctx)

    written = []

    def crash(name):
        written.append(name)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        apply(ctx, planned(ctx, checksum), checkpoint=crash)
    with pytest.raises(WorkspaceLayoutError, match="supplement"):
        with layout_lock(ctx.target.auth):
            pass
    preview = recover(ctx.target, ctx.target_env)
    assert preview["recovery_needed"] and not preview["conflicts"]
    path = ctx.target.catalog.parent / written[0]
    before = path.read_bytes()
    path.write_bytes(b"manual changes must be preserved")
    assert recover(ctx.target, ctx.target_env)["conflicts"] == written
    with pytest.raises(WorkspaceLayoutError, match="新增修改"):
        recover(ctx.target, ctx.target_env, apply=True, confirm_api_stopped=True)
    assert path.read_bytes() == b"manual changes must be preserved"
    path.write_bytes(before)
    result = recover(ctx.target, ctx.target_env, apply=True, confirm_api_stopped=True)
    assert result["recovered"]
    assert not marker_path(ctx.target).exists()


def test_live_api_lock_prevents_import(context):
    ctx = context
    checksum = exported(ctx)
    plan = planned(ctx, checksum)
    with layout_lock(ctx.target.auth), pytest.raises(WorkspaceLayoutError, match="停止"):
        apply(ctx, plan)


@pytest.mark.parametrize("mutation", ["tamper", "extra", "orphan", "profile-scope", "unknown-key"])
def test_bundle_validation_rejects_bad_content(context, mutation):
    ctx = context
    checksum = exported(ctx, keys=mutation == "unknown-key")
    if mutation == "tamper":
        (ctx.bundle / "category-profiles.json").write_text("{}", encoding="utf-8")
    elif mutation == "extra":
        (ctx.bundle / "unregistered.txt").write_text("unexpected", encoding="utf-8")
        checksum = refresh_manifest(ctx.bundle)
    elif mutation == "orphan":
        folder = ctx.bundle / "media" / str(uuid4())
        save(folder / "asset.json", {})
        checksum = refresh_manifest(ctx.bundle)
    elif mutation == "profile-scope":
        state = json.loads((ctx.bundle / "category-profiles.json").read_text("utf-8"))
        state["profiles"][0]["account_id"] = OTHER
        save(ctx.bundle / "category-profiles.json", state)
        checksum = refresh_manifest(ctx.bundle)
    else:
        manifest = json.loads((ctx.bundle / "manifest.json").read_text("utf-8"))
        encrypted = crypto(
            "seal",
            json_bytes(
                {
                    "format": "ViralDNA model keys",
                    "version": 1,
                    "bundle_id": manifest["id"],
                    "keys": {"VIRAL_DNA_AUTH_DB_PATH": "forbidden"},
                }
            ),
            ctx.unlock,
            NODE,
        )
        (ctx.bundle / "model-keys.vdna-secrets").write_bytes(encrypted)
        checksum = refresh_manifest(ctx.bundle)
    with pytest.raises((WorkspaceLayoutError, ValueError)):
        planned(ctx, checksum)


def test_wrong_key_and_skip_keys_explicit_option(context):
    ctx = context
    checksum = exported(ctx, keys=True)
    ctx.unlock.write_bytes(b"x" * 32)
    with pytest.raises(WorkspaceLayoutError, match="加解密"):
        planned(ctx, checksum)
    plan = planned(ctx, checksum, skip_keys=True)
    assert plan["model_keys_skipped"]
    original = ctx.target_env.read_bytes()
    apply(ctx, plan, skip_keys=True)
    assert ctx.target_env.read_bytes() == original


def test_cli_does_not_leak_secret_parse_errors(context, capsys):
    ctx = context
    checksum = exported(ctx)
    (ctx.bundle / "category-profiles.json").write_text("secret-invalid-json", encoding="utf-8")
    assert main(["verify", "--bundle", str(ctx.bundle), "--manifest-sha256", checksum]) == 1
    assert "secret-invalid-json" not in capsys.readouterr().err


def test_application_contracts_and_repeat_after_app_reserialization(context):
    from viral_dna_api.category_profiles.contracts import CategoryProfileState
    from viral_dna_api.platform_skills.presentation_models import SkillMediaAsset, SkillPresentation

    ctx = context
    checksum = exported(ctx)
    apply(ctx, planned(ctx, checksum))
    root = ctx.target.catalog.parent
    category_path = root / "category-profiles.json"
    categories = CategoryProfileState.model_validate_json(category_path.read_bytes())
    save(category_path, categories.model_dump(mode="json"))
    catalog_path = root / "platform-skills.json"
    state = json.loads(catalog_path.read_bytes())
    display = SkillPresentation.model_validate(state["skills"][0]["presentation"])
    state["skills"][0]["presentation"] = display.model_dump(mode="json")
    save(catalog_path, state)
    for metadata in (root / "platform-skill-media").glob("*/asset.json"):
        assert SkillMediaAsset.model_validate_json(metadata.read_bytes()).status == "ready"
    repeat = planned(ctx, checksum)
    assert not repeat["actions"] and not repeat["conflicts"]


@pytest.mark.parametrize("kind", ["wrong-kind", "missing-poster", "foreign-skill", "not-ready"])
def test_incomplete_or_cross_skill_media_are_refused(context, kind):
    ctx = context
    path = ctx.source.catalog.parent / "platform-skill-media" / ctx.asset_id / "asset.json"
    metadata = json.loads(path.read_bytes())
    if kind == "wrong-kind":
        metadata["kind"] = "image"
    elif kind == "missing-poster":
        metadata["poster_asset_id"] = None
    elif kind == "foreign-skill":
        metadata["skill_id"] = "platform.other"
    else:
        metadata["status"] = "processing"
    save(path, metadata)
    with pytest.raises(WorkspaceLayoutError):
        exported(ctx)
    assert not ctx.bundle.exists()


def test_other_accounts_deleted_profiles_and_missing_skill_are_preserved(context):
    ctx = context
    original = copy.deepcopy(ctx.category)
    original["deleted_at"] = "2026-09-12T01:00:00Z"
    save(
        ctx.source.catalog.parent / "category-profiles.json",
        {"schema_version": 1, "profiles": [ctx.category, profile("未选择账户", OTHER)]},
    )
    checksum = exported(ctx)
    extra = profile("正式其他账户", OTHER)
    save(
        ctx.target.catalog.parent / "category-profiles.json",
        {"schema_version": 1, "profiles": [extra, original]},
    )
    save(ctx.target.catalog.parent / "platform-skills.json", {"skills": [], "versions": []})
    plan = planned(ctx, checksum, keep_conflicts=True)
    assert {c["kind"] for c in plan["conflicts"]} == {"category", "skill"}
    assert not plan["actions"]
    apply(ctx, plan, keep_conflicts=True)
    current = json.loads((ctx.target.catalog.parent / "category-profiles.json").read_bytes())
    assert current["profiles"] == [extra, original]


def test_env_change_invalidates_preview_even_without_secret_transfer(context):
    ctx = context
    checksum = exported(ctx)
    plan = planned(ctx, checksum)
    with ctx.target_env.open("a", encoding="utf-8") as stream:
        stream.write("# admin edited configuration\n")
    with pytest.raises(WorkspaceLayoutError, match="重新预览"):
        apply(ctx, plan)


def test_path_aliases_and_directory_instead_of_file_fail_closed(context):
    ctx = context
    checksum = exported(ctx)
    with pytest.raises(WorkspaceLayoutError, match="相互包含"):
        plan_import(
            ctx.target, ctx.target_env, ctx.bundle, unlock=ctx.bundle / "secret.vdna-unlock"
        )
    (ctx.target.catalog.parent / "category-profiles.json").mkdir()
    with pytest.raises(WorkspaceLayoutError, match="目录占用"):
        planned(ctx, checksum)


def test_snapshot_env_parser_matches_application(tmp_path):
    from viral_dna_api.runtime_config import read_local_env

    raw = (
        b"\xef\xbb\xbf# comment\r\nDASHSCOPE_API_KEY='fixture-value'\n"
        b' ARK_API_KEY = "fixture-ark"\nNOT-A-KEY=ignored\nEMPTY=\n'
    )
    path = tmp_path / "api.env"
    path.write_bytes(raw)
    assert env_values(raw) == read_local_env(path)


def test_packaged_menu_runs_isolated_without_api_dependencies(context, tmp_path):
    root = Path(__file__).resolve().parents[3]
    packaging = runpy.run_path(str(root / "scripts/maintenance/build-supplement-package.py"))
    package = tmp_path / "copy.vdna-supplement-kit"
    result = packaging["build"](context.source, context.source_env, package, apply=True)
    assert result["zip_verified"] and not result["unlock_file"]
    assert not (package / "services/api/src/viral_dna_api/main.py").exists()
    bat = (package / "migrate.bat").read_bytes()
    assert bat.startswith(b"@echo off\r\n") and b"\n" not in bat.replace(b"\r\n", b"")
    with zipfile.ZipFile(result["zip"]) as zf:
        assert zf.testzip() is None
        assert all(not name.endswith(".vdna-unlock") for name in zf.namelist())
    server = tmp_path / "production"
    target, env = installation(server / ".server", target=True)
    auth_before = target.auth.read_bytes()
    command = [
        sys.executable,
        "-B",
        "-I",
        str(package / "scripts/maintenance/supplement-menu.py"),
        "--server-root",
        str(server),
    ]
    run = subprocess.run(command, input=b"2\n1\n2\nIMPORT\n0\n", capture_output=True, timeout=45)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    output = run.stdout.decode("utf-8", errors="replace")
    assert '"imported": true' in output
    assert target.auth.read_bytes() == auth_before
    assert (
        len(json.loads((target.catalog.parent / "category-profiles.json").read_bytes())["profiles"])
        == 1
    )
    assert "UNRELATED" in env.read_text("utf-8")
    repeated = subprocess.run(command, input=b"1\n2\nIMPORT\n0\n", capture_output=True, timeout=45)
    assert repeated.returncode == 0 and b'"idempotent": true' in repeated.stdout


def test_kit_excludes_unlock_and_tampered_tools_are_refused(context, tmp_path):
    if not NODE:
        pytest.skip("Node required")
    root = Path(__file__).resolve().parents[3]
    packaging = runpy.run_path(str(root / "scripts/maintenance/build-supplement-package.py"))
    menu = runpy.run_path(str(root / "scripts/maintenance/supplement-menu.py"))
    package = tmp_path / "secure.vdna-supplement-kit"
    preview = packaging["build"](
        context.source,
        context.source_env,
        package,
        include_keys=True,
        unlock=context.unlock,
        node=NODE,
    )
    assert preview["preview"] and not package.exists() and not context.unlock.exists()
    result = packaging["build"](
        context.source,
        context.source_env,
        package,
        apply=True,
        include_keys=True,
        unlock=context.unlock,
        node=NODE,
    )
    assert context.unlock.is_file()
    assert menu["verify_kit"](package)["unlock_file_name"] == context.unlock.name
    with zipfile.ZipFile(result["zip"]) as zf:
        for name in zf.namelist():
            assert not name.endswith(".vdna-unlock")
            assert b"fixture-source-secret" not in zf.read(name)
    (package / "scripts/maintenance/supplement-menu.py").write_bytes(b"changed")
    with pytest.raises(WorkspaceLayoutError, match="校验失败"):
        menu["verify_kit"](package)


def test_preview_digest_is_stable_across_independent_cli_processes(context):
    ctx = context
    checksum = exported(ctx)
    root = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        str(root / "scripts/maintenance/transfer-supplement.py"),
        "import",
        "--env-file",
        str(ctx.target_env),
        "--bundle",
        str(ctx.bundle),
        "--manifest-sha256",
        checksum,
    ]
    reports = []
    for seed in ("1", "2"):
        result = subprocess.run(
            command, capture_output=True, timeout=45, env={**os.environ, "PYTHONHASHSEED": seed}
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        reports.append(json.loads(result.stdout))
    assert reports[0]["plan_sha256"] == reports[1]["plan_sha256"]


def test_invalid_target_json_is_not_replaced_as_if_empty(context):
    ctx = context
    checksum = exported(ctx)
    path = ctx.target.catalog.parent / "category-profiles.json"
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        planned(ctx, checksum)
    assert path.read_bytes() == b""
