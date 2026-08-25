from __future__ import annotations

import asyncio
import os
import subprocess
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

ChunkHandler = Callable[[str], Awaitable[None] | None]


class EnhancementProcessError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        output_tail: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.output_tail = output_tail[-6000:]


class EnhancementProcessTimeout(EnhancementProcessError):
    pass


class EnhancementProcessCancelled(EnhancementProcessError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def _call_handler(handler: ChunkHandler | None, chunk: str) -> None:
    if handler is None or not chunk:
        return
    result = handler(chunk)
    if result is not None:
        await result


async def _pump_stream(
    stream: asyncio.StreamReader | None,
    handler: ChunkHandler | None,
    tail: deque[str],
) -> None:
    if stream is None:
        return
    while True:
        payload = await stream.read(1024)
        if not payload:
            return
        chunk = payload.decode("utf-8", errors="replace")
        tail.append(chunk)
        await _call_handler(handler, chunk)


async def terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill.exe",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await killer.wait()
    elif process.returncode is None:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.wait()


class AsyncEnhancementProcessRunner:
    async def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int,
        cancellation: asyncio.Event,
        on_stdout: ChunkHandler | None = None,
        on_stderr: ChunkHandler | None = None,
        on_started: Callable[[int], Awaitable[None] | None] | None = None,
    ) -> ProcessResult:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd) if cwd is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise EnhancementProcessError(f"无法启动视频清晰化进程：{exc}") from exc
        if on_started is not None:
            started_result = on_started(process.pid)
            if started_result is not None:
                await started_result

        stdout_tail: deque[str] = deque(maxlen=64)
        stderr_tail: deque[str] = deque(maxlen=64)
        stdout_task = asyncio.create_task(_pump_stream(process.stdout, on_stdout, stdout_tail))
        stderr_task = asyncio.create_task(_pump_stream(process.stderr, on_stderr, stderr_tail))
        wait_task = asyncio.create_task(process.wait())
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                {wait_task, cancel_task},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done and cancellation.is_set():
                await terminate_process_tree(process)
                raise EnhancementProcessCancelled("视频清晰化已取消")
            if wait_task not in done:
                await terminate_process_tree(process)
                tail = "".join(stderr_tail or stdout_tail)
                raise EnhancementProcessTimeout(
                    f"视频清晰化超过 {timeout_seconds} 秒仍未完成",
                    output_tail=tail,
                )
            returncode = await wait_task
            await asyncio.gather(stdout_task, stderr_task)
            stdout = "".join(stdout_tail)
            stderr = "".join(stderr_tail)
            if returncode != 0:
                raise EnhancementProcessError(
                    "视频清晰化进程返回失败状态",
                    returncode=returncode,
                    output_tail=stderr or stdout,
                )
            return ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr)
        finally:
            cancel_task.cancel()
            if not stdout_task.done():
                stdout_task.cancel()
            if not stderr_task.done():
                stderr_task.cancel()
