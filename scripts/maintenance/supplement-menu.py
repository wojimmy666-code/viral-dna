"""Small offline menu shipped inside a self-contained supplemental migration kit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api/src"))

from viral_dna_api.accounts.installation_bundle import (
    Settings,
    inventory,
    json_bytes,
    portable_name,
)
from viral_dna_api.accounts.supplement_data import read_bytes, verify_bundle
from viral_dna_api.accounts.supplement_transfer import (
    apply_import,
    plan_import,
    recover,
)
from viral_dna_api.accounts.workspace_layout import WorkspaceLayoutError, checked_path


def verify_kit(package):
    package = checked_path(package)
    spec = json.loads((package / "kit.json").read_text("utf-8"))
    if spec.get("format") != "ViralDNA supplement kit" or spec.get("version") != 1:
        raise WorkspaceLayoutError("补充工具包格式不受支持")
    entries = inventory(package, hashes=True)
    entries.pop("kit.json", None)
    if entries != spec.get("files"):
        raise WorkspaceLayoutError("工具包文件校验失败，请重新复制或解压，不要继续导入")
    key_name = spec.get("unlock_file_name")
    if key_name is not None:
        portable_name(key_name)
        if "/" in key_name or not key_name.endswith(".vdna-unlock"):
            raise WorkspaceLayoutError("解锁文件名不正确")
    verify_bundle(package / "payload.vdna-supplement", spec["manifest_sha256"])
    return spec


def run_menu(package, server, *, read=input, write=print):
    package, server = checked_path(package), checked_path(server)
    spec = verify_kit(package)
    env_file = server / ".server/config/api.env"
    node = server / ".server/tools/node/node.exe"
    unlock = (
        server / ".server/migration-secrets" / spec["unlock_file_name"]
        if spec.get("unlock_file_name")
        else None
    )
    bundle = package / "payload.vdna-supplement"
    keep_conflicts = skip_keys = False
    preview = recovery_preview = None
    write("ViralDNA 补充迁移：只补品类、Skill 展示素材和选定模型密钥。")
    write("不改手机号、密码、账户目录或项目；不自动停止/启动服务，也不更改 IIS。")
    write(f"目标配置：{env_file}")
    if unlock:
        write(f"解锁文件应单独放在：{unlock}")

    def report(value):
        write(json.dumps(value, ensure_ascii=False, indent=2))
        # Reports contain paths/hashes/key names only; never values or decrypted content.
        folder = checked_path(server / ".server/migration-reports")
        folder.mkdir(parents=True, exist_ok=True)
        filename = folder / f"supplement-{uuid4()}.json"
        with filename.open("xb") as output:
            output.write(json_bytes(value))
        write(f"报告：{filename}")

    while True:
        write("\n1. 预览补充导入  2. 执行刚才的预览  3. 预览故障恢复  4. 执行恢复")
        write("5. 切换冲突处理  6. 切换是否导入模型密钥  0. 退出")
        write(
            f"冲突：{'保留正式端，仅补其他项' if keep_conflicts else '暂停导入'}；"
            f"模型密钥：{'跳过' if skip_keys else '补齐缺项'}"
        )
        choice = read("请选择：").strip()
        if choice == "0":
            return 0
        if choice in {"5", "6"}:
            if choice == "5":
                keep_conflicts = not keep_conflicts
            else:
                skip_keys = not skip_keys
            preview = None
            write("选项已改变，请重新按 1 预览。不会覆盖正式端的冲突内容。")
            continue
        try:
            # Check shipped code and media again before each operation.
            verify_kit(package)
            settings = Settings.from_env(env_file, target=True)
            if choice in {"1", "2"} and unlock and not skip_keys and not node.is_file():
                raise WorkspaceLayoutError(f"未找到服务器 Node 运行程序：{node}")
            options = {
                "expected_digest": spec["manifest_sha256"],
                "unlock": unlock,
                "node": str(node),
                "keep_conflicts": keep_conflicts,
                "skip_keys": skip_keys,
            }
            if choice == "1":
                preview = None
                preview, _ = plan_import(settings, env_file, bundle, **options)
                report(preview)
                write(
                    f"待补品类 {len(preview['add_categories'])} 个；"
                    f"Skill 展示 {len(preview['update_skill_presentations'])} 个；"
                    f"模型密钥 {len(preview['add_model_keys'])} 项；"
                    f"冲突 {len(preview['conflicts'])} 项。"
                )
                if not preview["ready"]:
                    write(
                        "有冲突，不能按 2 导入。核对报告后，可按 5 保留正式端并重新预览。"
                    )
            elif choice == "2":
                if preview is None or not preview["ready"]:
                    write("请先按 1，获得可执行的预览。")
                    continue
                write("请先停止本项目服务及 ViralDNA 站点入口；不要停止其他 IIS 站点。")
                if read("确认已停服并同意本次预览，输入 IMPORT：").strip() != "IMPORT":
                    write("已取消，没有导入。")
                    continue
                selected_plan, preview = preview, None
                result = apply_import(
                    settings,
                    env_file,
                    bundle,
                    expected_plan=selected_plan["plan_sha256"],
                    confirm_api_stopped=True,
                    **options,
                )
                report(result)
                write("补充导入完成。可启动本项目服务、恢复 ViralDNA 站点并验收。")
            elif choice == "3":
                recovery_preview = recover(
                    settings, env_file, unlock=unlock, node=str(node)
                )
                report(recovery_preview)
            elif choice == "4":
                if (
                    not recovery_preview
                    or not recovery_preview.get("recovery_needed")
                    or recovery_preview.get("conflicts")
                ):
                    write("请先按 3，确认需要恢复且没有冲突。")
                    continue
                if (
                    read("确认已停服，输入 RECOVER 恢复中断前的数据：").strip()
                    != "RECOVER"
                ):
                    continue
                current = recover(settings, env_file, unlock=unlock, node=str(node))
                if current != recovery_preview:
                    raise WorkspaceLayoutError("恢复预览已变化，请重新按 3 检查")
                result = recover(
                    settings,
                    env_file,
                    apply=True,
                    confirm_api_stopped=True,
                    unlock=unlock,
                    node=str(node),
                )
                recovery_preview = None
                report(result)
            else:
                write("请选择菜单中的数字。")
        except Exception as error:  # noqa: BLE001 - never print secret-bearing parse errors
            # Do not echo JSON errors or subprocess diagnostics that could contain credentials.
            message = (
                str(error)
                if isinstance(error, WorkspaceLayoutError)
                else "配置或文件检查失败"
            )
            write(f"未完成：{message}")
            preview = recovery_preview = None
            if unlock and read_bytes(unlock) is None:
                write(
                    "未找到单独的解锁文件；请按上方路径复制，或按 6 明确跳过模型密钥。"
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description="ViralDNA 补充迁移离线菜单")
    parser.add_argument(
        "--package", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--server-root", type=Path, default=Path("C:/Projects/ViralDNA")
    )
    args = parser.parse_args(argv)
    try:
        return run_menu(args.package, args.server_root)
    except (EOFError, KeyboardInterrupt):
        print("操作已中断；若导入已开始，请保持停服，下次先按 3 检查恢复。")
        return 130
    except Exception as error:  # noqa: BLE001 - terminal boundary redacts secret-bearing errors
        message = (
            str(error)
            if isinstance(error, WorkspaceLayoutError)
            else "工具包或配置检查失败"
        )
        print(f"未执行：{message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
