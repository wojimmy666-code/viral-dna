"""No-charge protocol tests: the child server and generated images are fixtures."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

import pytest
from test_image_streaming import WRAPPER, wrapper_functions

FAKE_SERVER = r"""
import json, os, sys, time
from io import BytesIO
from pathlib import Path
from PIL import Image

if "--version" in sys.argv:
    print("codex-cli test")
    raise SystemExit(0)
root = Path.cwd()
mode = os.getenv("SERVER_TEST_MODE", "complete")
home = Path(os.environ["CODEX_HOME"])
own = home / "generated_images" / "own-thread-1234"
own.mkdir(parents=True, exist_ok=True)

def write(value):
    print(json.dumps(value), flush=True)

def event(method, **params):
    write({"method": method, "params": {
        "threadId": "own-thread-1234", "turnId": "turn-1", **params}})

def image_item(index, state="completed", foreign=False):
    directory = home / "generated_images" / "other-thread-1234" if foreign else own
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (str(index) + ".png")
    item = {"id": "image-" + str(index), "type": "imageGeneration",
            "status": "in_progress", "result": ""}
    if mode != "no_image_events":
        event("item/started", item=item)
    content = BytesIO()
    Image.new("RGB", (48, 48), "blue").save(content, format="PNG")
    path.write_bytes(content.getvalue()[:24] if mode == "incomplete" else content.getvalue())
    if mode == "file_without_event":
        wait_release()
    item.update(status=state, savedPath=str(path))
    if mode != "no_image_events":
        event("item/completed", item=item)
    if mode == "incomplete":
        wait_release()
        path.write_bytes(content.getvalue())

def wait_release():
    deadline = time.monotonic() + 10
    while not (root / "release").exists():
        if time.monotonic() > deadline:
            raise SystemExit("release timeout")
        time.sleep(.02)

for line in sys.stdin:
    message = json.loads(line)
    with (root / "requests.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(message) + "\n")
    method, params = message.get("method"), message.get("params", {})
    if method is None and message.get("id") == 900:
        assert "error" in message
        event("turn/completed", turn={"id": "turn-1", "status": "failed"})
        continue
    result = {}
    if method == "initialize":
        result = {"userAgent": "fixture"}
    elif method == "skills/list":
        skills = [] if mode == "no_skill" else [{
            "name": "imagegen", "scope": "system", "enabled": True,
            "path": str(home / "skills" / ".system" / "imagegen" / "SKILL.md")}]
        result = {"data": [{"cwd": str(root), "skills": skills}]}
    elif method == "thread/start":
        result = {"thread": {"id": "own-thread-1234"}, "model": params["model"],
            "modelProvider": params["modelProvider"], "approvalPolicy": "never",
            "sandbox": {"type": "workspaceWrite"}, "cwd": str(root)}
        if mode == "wrong_model":
            result["model"] = "other-model"
        if mode == "wrong_sandbox":
            result["sandbox"]["type"] = "dangerFullAccess"
        if mode == "wrong_cwd":
            result["cwd"] = str(root.parent)
        if mode == "wrong_network":
            result["sandbox"]["networkAccess"] = True
    elif method == "turn/start":
        write({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
        event("turn/started", turn={"id": "turn-1"})
        if mode == "request_approval":
            write({"id": 900, "method": "item/permissions/requestApproval", "params": {}})
            continue
        if mode == "inflight":
            event("item/started", item={"id": "other-tool", "type": "commandExecution"})
        image_item(1, foreign=(mode == "foreign"))
        if mode in {"multi", "inflight", "foreign"}:
            wait_release()
        if mode == "multi":
            image_item(2)
        if mode == "foreign":
            image_item(2)
        if mode == "inflight":
            event("item/completed", item={"id": "other-tool", "type": "commandExecution"})
        if mode == "failed_partial":
            event("turn/completed", turn={"id": "turn-1", "status": "failed"})
        if mode in {"normal_end", "no_image_events"}:
            event("turn/completed", turn={"id": "turn-1", "status": "completed"})
        continue
    elif method == "turn/interrupt":
        write({"id": message["id"], "result": {}})
        event("turn/completed", turn={"id": "turn-1", "status": "interrupted"})
        if mode == "late_exit":
            time.sleep(15)
        continue
    if "id" in message:
        write({"id": message["id"], "result": result})
"""


def prepare(tmp_path, mode="complete", count=1):
    root = tmp_path / "run"
    root.mkdir()
    server = tmp_path / "server.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    request = root / "request.json"
    request.write_text(
        json.dumps(
            {
                "protocol_version": "viral-dna-image-tool/v1",
                "request_id": "task-1234",
                "candidate_count": count,
                "output": {"width": 48, "height": 48},
                "prompt": {"positive": "保留产品结构和中文画面要求", "negative": "不要额外文字"},
                "inputs": [],
            }
        ),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(WRAPPER),
        "--codex-executable",
        sys.executable,
        "--codex-fixed-arg",
        str(server),
        "--codex-timeout",
        "12",
        "generate",
        "--request",
        str(request),
        "--output",
        str(root / "tool-output"),
    ]
    env = {**os.environ, "CODEX_HOME": str(tmp_path / "codex"), "SERVER_TEST_MODE": mode}
    return root, command, env


def requests(root):
    path = root / "requests.jsonl"
    return (
        [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
    )


def run(command, env):
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.mark.parametrize("mode", ["complete", "late_exit", "normal_end", "no_image_events"])
def test_explicit_skill_and_completed_images_finish_without_text_tail(tmp_path, mode):
    root, command, env = prepare(tmp_path, mode)
    started = time.monotonic()
    result = run(command, env)
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 8  # The fixture's 15-second tail is never awaited.
    calls = requests(root)
    turn = next(call["params"] for call in calls if call.get("method") == "turn/start")
    assert turn["input"][1]["type"] == "skill"
    assert turn["input"][1]["name"] == "imagegen"
    assert turn["input"][0]["text"].startswith("$imagegen\n")
    assert "保留产品结构和中文画面要求" in turn["input"][0]["text"]
    assert turn["effort"] == "medium" and turn["model"] == "gpt-5.6-sol"
    assert sum(call.get("method") == "turn/start" for call in calls) == 1
    manifest = json.loads((root / "tool-output" / "result.json").read_text("utf-8"))
    assert manifest["usage"]["codex_runner"] == "app-server"
    assert manifest["usage"]["model_transport"] == "https"
    assert len(manifest["candidates"]) == 1
    phases = [event["phase"] for event in manifest["usage"]["timing"]["events"]]
    if mode == "no_image_events":
        assert manifest["usage"]["timing"]["durations_ms"]["first_image_tool_ms"] is None
        assert "interrupt_requested" not in phases
    else:
        assert phases.index("image_tool_completed") < phases.index("process_stopped")
    if mode not in {"normal_end", "no_image_events"}:
        assert (
            phases.index("image_tool_completed")
            < phases.index("interrupt_requested")
            < phases.index("turn_ended")
        )
    assert "skill_discovered" in phases
    assert "skill_input_submitted" in phases
    assert not (tmp_path / "codex" / "config.toml").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,count",
    [("file_without_event", 1), ("multi", 2), ("inflight", 1), ("foreign", 1), ("incomplete", 1)],
)
async def test_files_partial_results_and_foreign_outputs_never_end_live_tools(
    tmp_path, mode, count
):
    root, command, env = prepare(tmp_path, mode, count)
    task = asyncio.create_task(asyncio.to_thread(run, command, env))
    try:
        deadline = time.monotonic() + 7
        while not (
            tmp_path
            / "codex"
            / "generated_images"
            / ("other-thread-1234" if mode == "foreign" else "own-thread-1234")
            / "1.png"
        ).exists():
            assert time.monotonic() < deadline
            if task.done():
                pytest.fail((await task).stderr)
            await asyncio.sleep(0.025)
        await asyncio.sleep(0.4)
        assert not task.done()
        assert not any(call.get("method") == "turn/interrupt" for call in requests(root))
        assert not (root / "tool-output" / "result.json").exists()
    finally:
        (root / "release").touch()
        result = await task
    assert result.returncode == 0, result.stderr
    manifest = json.loads((root / "tool-output" / "result.json").read_text("utf-8"))
    assert len(manifest["candidates"]) == count


@pytest.mark.parametrize(
    "mode", ["no_skill", "wrong_model", "wrong_sandbox", "wrong_cwd", "wrong_network"]
)
def test_runtime_refuses_invalid_setup_before_generation(tmp_path, mode):
    root, command, env = prepare(tmp_path, mode)
    result = run(command, env)
    assert result.returncode != 0
    assert not any(call.get("method") == "turn/start" for call in requests(root))
    assert not (root / "tool-output" / "result.json").exists()
    assert (root / "tool-output" / "timing.json").exists()


def test_partial_failure_keeps_published_image_and_timings_without_resubmission(tmp_path):
    root, command, env = prepare(tmp_path, "failed_partial", count=2)
    result = run(command, env)
    assert result.returncode != 0
    progress = json.loads((root / "tool-output" / "progress.json").read_text("utf-8"))
    assert len(progress["candidates"]) == 1
    assert (root / "tool-output" / progress["candidates"][0]["path"]).exists()
    assert (root / "tool-output" / "timing.json").exists()
    assert sum(call.get("method") == "turn/start" for call in requests(root)) == 1


def test_unsolicited_permission_requests_are_never_approved(tmp_path):
    root, command, env = prepare(tmp_path, "request_approval")
    result = run(command, env)
    assert result.returncode != 0
    response = next(call for call in requests(root) if call.get("id") == 900)
    assert "error" in response
    assert "result" not in response
    assert not (root / "tool-output" / "result.json").exists()


def test_default_runtime_is_stdio_https_with_unchanged_approval_boundary():
    adapter = wrapper_functions()
    args = adapter["_parser"]().parse_args(["--codex-executable", sys.executable, "capabilities"])
    command = adapter["_app_server_command"](args)
    assert command[-2:] == ["app-server", "--stdio"]
    assert "supports_websockets=false" in " ".join(command)
    assert 'approval_policy="never"' in command
    assert 'sandbox_mode="workspace-write"' in command
    assert "sandbox_workspace_write.writable_roots=[]" in command
    assert "sandbox_workspace_write.network_access=false" in command
    assert not any("ignore-rules" in arg or "danger" in arg for arg in command)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path syntax")
def test_path_identity_preserves_task_scope_across_windows_path_spellings(tmp_path):
    adapter = wrapper_functions()
    key = adapter["canonical_path_key"]
    assert key(tmp_path) == key("\\\\?\\" + str(tmp_path))
    assert key(tmp_path) != key(tmp_path.parent)


def test_image_tool_timing_matches_item_ids_and_keeps_unobserved_phases_null():
    timing = wrapper_functions()["GenerationTiming"]()
    timing.events = [
        {"phase": "image_tool_started", "elapsed_ms": 10, "item_id": "first"},
        {"phase": "image_tool_started", "elapsed_ms": 20, "item_id": "second"},
        {
            "phase": "image_tool_completed",
            "elapsed_ms": 40,
            "item_id": "second",
            "status": "completed",
        },
        {
            "phase": "image_tool_completed",
            "elapsed_ms": 60,
            "item_id": "first",
            "status": "completed",
        },
    ]
    result = timing.snapshot()
    assert result["durations_ms"]["first_image_tool_ms"] == 20
    assert [item["elapsed_ms"] for item in result["image_tools"]] == [20, 50]
    assert result["durations_ms"]["skill_discovery_ms"] is None
