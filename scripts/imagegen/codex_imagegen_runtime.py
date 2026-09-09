"""One isolated Codex app-server turn, using the installed built-in ImageGen skill.

This is local stdio control of Codex, not an Images API client. No auth/config
files are copied or changed. A rendered file alone never authorizes interruption.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any


def canonical_path_key(value: str | Path) -> str:
    """Compare Windows extended/ordinary spellings without changing IO paths."""
    resolved = str(Path(value).resolve())
    if os.name == "nt":
        if resolved.startswith("\\\\?\\UNC\\"):
            resolved = "\\\\" + resolved[8:]
        elif resolved.startswith("\\\\?\\"):
            resolved = resolved[4:]
    return os.path.normcase(resolved)


class GenerationTiming:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.events: list[dict[str, Any]] = []
        self.mark("adapter_started")

    def mark(self, name: str, **details: Any) -> None:
        self.events.append(
            {
                "phase": name,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                **details,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        first = {}
        for event in self.events:
            first.setdefault(event["phase"], event["elapsed_ms"])
        intervals = {
            "version_check_ms": ("adapter_started", "version_checked"),
            "process_start_ms": ("process_launch_started", "process_started"),
            "server_initialization_ms": ("process_started", "server_initialized"),
            "skill_discovery_ms": ("skill_lookup_started", "skill_discovered"),
            "thread_setup_ms": ("skill_discovered", "thread_started"),
            "dispatch_to_first_image_tool_ms": ("turn_submitted", "image_tool_started"),
            "dispatch_to_first_image_ms": ("turn_submitted", "first_image_published"),
            "image_to_turn_end_ms": ("all_images_published", "turn_ended"),
            "process_cleanup_ms": ("turn_ended", "process_stopped"),
        }
        image_starts = {
            event["item_id"]: event["elapsed_ms"]
            for event in self.events
            if event["phase"] == "image_tool_started"
        }
        image_tools = [
            {
                "item_id": event["item_id"],
                "status": event.get("status"),
                "elapsed_ms": event["elapsed_ms"] - image_starts[event["item_id"]],
            }
            for event in self.events
            if event["phase"] == "image_tool_completed"
            and event["item_id"] in image_starts
        ]
        return {
            "schema_version": "viral-dna-image-timing/v1",
            "started_at": self.started_at,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "durations_ms": {
                **{
                    name: first[end] - first[start]
                    if start in first and end in first
                    else None
                    for name, (start, end) in intervals.items()
                },
                "first_image_tool_ms": image_tools[0]["elapsed_ms"]
                if image_tools
                else None,
            },
            "image_tools": image_tools,
            "events": list(self.events),
        }


def stop_owned_process(process: subprocess.Popen, *, grace_seconds: float = 1) -> None:
    """Release only this owned subprocess tree; never release a live generation slot."""
    if process.stdin and not process.stdin.closed:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def run_imagegen_server(
    command: list[str],
    *,
    cwd: Path,
    model: str,
    reasoning_effort: str,
    provider: str,
    prompt: str,
    inputs: list[tuple[str, Path]],
    expected_count: int,
    timeout_seconds: int,
    timing: GenerationTiming,
    on_update: Callable[[str, str], None],
    completed_images_are_valid: Callable[[set[str]], bool],
    preflight_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    timing.mark("process_launch_started")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    timing.mark("process_started", transport="stdio", runner="app-server")
    queue: Queue[tuple[str, str | None]] = Queue(maxsize=256)
    stopped = False

    def read_pipe(name, pipe):
        try:
            for line in iter(pipe.readline, ""):
                if stopped:
                    break
                queue.put((name, line))
        finally:
            pipe.close()
            queue.put((name, None))

    threads = [
        Thread(target=read_pipe, args=(name, pipe), daemon=True)
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_seconds
    request_id = 0
    pending: dict[int, str] = {}
    stdout = ""
    stderr = ""
    thread_id = None
    turn_id = None
    skill_path = None
    completed_paths: set[str] = set()
    active_tools: set[str] = set()
    completion_requested = False
    turn_ended = False
    close_reason = "turn_completed"
    interrupt_deadline = None
    failure = None
    usage = {}

    def send(method, params=None, *, notification=False):
        nonlocal request_id
        message = {"method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            request_id += 1
            message["id"] = request_id
            pending[request_id] = method
        # JSON escaping preserves Chinese losslessly even for Windows child
        # launchers that still inherit a legacy stdin code page.
        process.stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
        process.stdin.flush()

    def emit(event):
        nonlocal stdout
        stdout = (stdout + json.dumps(event, ensure_ascii=False) + "\n")[-1024 * 1024 :]
        on_update(stdout, stderr)

    try:
        send(
            "initialize",
            {
                "clientInfo": {"name": "viraldna_imagegen", "version": "1.4.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        while not turn_ended:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Codex ImageGen 执行超时；未自动重试，已发布图片保留"
                )
            if interrupt_deadline and time.monotonic() >= interrupt_deadline:
                raise RuntimeError(
                    "图片已完成，但 Codex 未确认结束收尾；已发布图片保留"
                )
            try:
                pipe, line = queue.get(timeout=0.25)
            except Empty:
                pipe, line = "idle", ""
            if line is None:
                if pipe == "stdout":
                    raise RuntimeError("Codex 控制进程提前退出，未收到任务完成确认")
                continue
            if pipe == "stderr":
                stderr = (stderr + line)[-1024 * 1024 :]
            elif pipe == "stdout":
                try:
                    message = json.loads(line)
                except ValueError:
                    raise RuntimeError("Codex 控制接口返回了无效 JSON") from None
                # Never approve unsolicited permission/tool requests in unattended work.
                if "method" in message and "id" in message:
                    process.stdin.write(
                        json.dumps(
                            {
                                "id": message["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "ViralDNA does not grant interactive requests",
                                },
                            }
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                    timing.mark("interactive_request_denied", method=message["method"])
                    continue
                if "id" in message:
                    method = pending.pop(message["id"], None)
                    if "error" in message:
                        raise RuntimeError(
                            f"Codex {method} 失败：{str(message['error'].get('message', '未知错误'))[:400]}"
                        )
                    result = message.get("result") or {}
                    if method == "initialize":
                        timing.mark("server_initialized")
                        send("initialized", notification=True)
                        timing.mark("skill_lookup_started")
                        send("skills/list", {"cwds": [str(cwd)]})
                    elif method == "skills/list":
                        matches = [
                            skill
                            for entry in result.get("data", [])
                            if canonical_path_key(entry.get("cwd", ""))
                            == canonical_path_key(cwd)
                            for skill in entry.get("skills", [])
                            if skill.get("name") == "imagegen"
                            and skill.get("enabled", True)
                        ]
                        # Select the installed system skill, never a project name collision.
                        matches = [
                            skill
                            for skill in matches
                            if skill.get("scope") == "system"
                            and Path(skill.get("path", "")).parts[-4:]
                            == ("skills", ".system", "imagegen", "SKILL.md")
                        ]
                        if len(matches) != 1:
                            raise RuntimeError(
                                "未找到唯一启用的系统 ImageGen 技能；没有发起图片生成"
                            )
                        skill_path = matches[0]["path"]
                        timing.mark(
                            "skill_discovered",
                            mode="explicit_skill_input",
                            path=skill_path,
                        )
                        send(
                            "thread/start",
                            {
                                "model": model,
                                "modelProvider": provider,
                                "cwd": str(cwd),
                                "approvalPolicy": "never",
                                "sandbox": "workspace-write",
                                "ephemeral": True,
                                "allowProviderModelFallback": False,
                                "runtimeWorkspaceRoots": [str(cwd)],
                                "config": {"model_reasoning_effort": reasoning_effort},
                            },
                        )
                    elif method == "thread/start":
                        if (
                            result.get("model") != model
                            or result.get("modelProvider") != provider
                            or result.get("approvalPolicy") != "never"
                            or result.get("sandbox", {}).get("type") != "workspaceWrite"
                            or result.get("sandbox", {}).get("networkAccess") is True
                            or not result.get("cwd")
                            or canonical_path_key(result["cwd"])
                            != canonical_path_key(cwd)
                        ):
                            raise RuntimeError(
                                "Codex 未保持指定模型、HTTPS provider 或工作区沙箱；没有发起图片生成"
                            )
                        thread_id = result["thread"]["id"]
                        timing.mark("thread_started")
                        emit({"type": "thread.started", "thread_id": thread_id})
                        if preflight_only:
                            turn_ended = True
                            close_reason = "preflight_only"
                            continue
                        user_inputs = [
                            {"type": "text", "text": "$imagegen\n" + prompt},
                            {"type": "skill", "name": "imagegen", "path": skill_path},
                        ]
                        user_inputs.extend(
                            {"type": "localImage", "path": str(path)}
                            for _, path in inputs
                        )
                        timing.mark("turn_submitted")
                        timing.mark(
                            "skill_input_submitted", mode="explicit_skill_input"
                        )
                        send(
                            "turn/start",
                            {
                                "threadId": thread_id,
                                "model": model,
                                "effort": reasoning_effort,
                                "input": user_inputs,
                            },
                        )
                    elif method == "turn/start":
                        turn_id = result["turn"]["id"]
                    elif method == "turn/interrupt":
                        timing.mark("interrupt_acknowledged")
                else:
                    method = message.get("method")
                    params = message.get("params") or {}
                    if not thread_id or params.get("threadId") != thread_id:
                        continue
                    incoming_turn = params.get("turnId") or (
                        params.get("turn") or {}
                    ).get("id")
                    if turn_id and incoming_turn and incoming_turn != turn_id:
                        continue
                    if method == "turn/started":
                        turn_id = params["turn"]["id"]
                        timing.mark("turn_started")
                        emit({"type": "turn.started"})
                    elif method in {"item/started", "item/completed"}:
                        item = params.get("item") or {}
                        kind, item_id = item.get("type"), item.get("id")
                        if kind not in {
                            "agentMessage",
                            "userMessage",
                            "reasoning",
                            "plan",
                        }:
                            if method == "item/started":
                                active_tools.add(item_id)
                            else:
                                active_tools.discard(item_id)
                        if kind == "imageGeneration":
                            if method == "item/started":
                                timing.mark("image_tool_started", item_id=item_id)
                            else:
                                timing.mark(
                                    "image_tool_completed",
                                    item_id=item_id,
                                    status=item.get("status"),
                                )
                            if (
                                method == "item/completed"
                                and item.get("status") == "completed"
                                and item.get("savedPath")
                            ):
                                path = str(item["savedPath"])
                                completed_paths.add(path)
                                emit(
                                    {
                                        "type": "item.completed",
                                        "item": {
                                            "id": item_id,
                                            "type": "image_generation",
                                            "status": "completed",
                                            "result": {"output_hint": path},
                                        },
                                    }
                                )
                        elif kind == "agentMessage" and method == "item/completed":
                            emit(
                                {
                                    "type": "item.completed",
                                    "item": {
                                        "type": "agent_message",
                                        "text": item.get("text", ""),
                                    },
                                }
                            )
                        else:
                            timing.mark(
                                "tool_started"
                                if method == "item/started"
                                else "tool_completed",
                                item_id=item_id,
                                kind=kind,
                            )
                    elif method == "thread/tokenUsage/updated":
                        usage = (params.get("tokenUsage") or {}).get("total") or {}
                    elif method == "turn/completed":
                        status = params["turn"]["status"]
                        timing.mark("turn_ended", status=status)
                        if status != "completed" and not (
                            status == "interrupted" and completion_requested
                        ):
                            failure = f"Codex 任务未正常完成（{status}）；已发布图片保留，不自动重试"
                        turn_ended = True
                        emit(
                            {
                                "type": "turn.completed"
                                if failure is None
                                else "turn.failed",
                                "usage": usage,
                            }
                        )
            on_update(stdout, stderr)
            if (
                not preflight_only
                and not turn_ended
                and not completion_requested
                and turn_id
                and len(completed_paths) >= expected_count
                and not active_tools
                and completed_images_are_valid(completed_paths)
            ):
                # This cancels only post-generation assistant work, not an in-flight image tool.
                completion_requested = True
                close_reason = "validated_image_completion"
                timing.mark("interrupt_requested", reason=close_reason)
                send("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                interrupt_deadline = time.monotonic() + 10
        if failure:
            raise RuntimeError(failure)
    except Exception as exc:
        close_reason = "failed"
        timing.mark("runtime_failed", error_type=type(exc).__name__)
        raise
    finally:
        stop_owned_process(process)
        stopped = True
        for thread in threads:
            thread.join(timeout=0.5)
        timing.mark(
            "process_stopped", reason=close_reason, exit_code=process.returncode
        )
        on_update(stdout, stderr)
    return subprocess.CompletedProcess(command, 0, stdout, stderr)
