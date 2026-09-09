"""Single-process production host with an instance-scoped graceful stop request.

No HTTP shutdown endpoint is exposed. Only an ACL-protected local control file
with the current random instance token can ask Uvicorn to run its shutdown hooks.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def process_started_at() -> str:
    if os.name != "nt":
        return datetime.now(UTC).isoformat()
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return datetime.fromtimestamp(ticks / 10_000_000 - 11_644_473_600, UTC).isoformat()


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def stop_requested(path: Path, token: str) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and value.get("token") == token


async def serve(args: argparse.Namespace) -> int:
    import uvicorn
    from viral_dna_api.runtime_config import read_local_env

    # Explicit configuration wins over machine/user defaults, including callers
    # which still read os.environ directly rather than get_config_value().
    os.environ.update(read_local_env(Path(args.env_file)))
    os.environ["VIRAL_DNA_ENV_FILE"] = args.env_file
    if os.environ.get("VIRAL_DNA_AUTH_MODE") != "password":
        raise RuntimeError("Production requires VIRAL_DNA_AUTH_MODE=password")
    server = uvicorn.Server(uvicorn.Config(
        "viral_dna_api.main:app", host="127.0.0.1", port=args.port,
        workers=1, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
        timeout_graceful_shutdown=args.stop_timeout,
    ))
    token = uuid.uuid4().hex
    state = {
        "pid": os.getpid(), "startedAt": process_started_at(), "token": token,
        "releaseId": args.release_id, "executable": sys.executable,
    }
    write_json(Path(args.state_file), state)

    async def watch_stop() -> None:
        while not server.should_exit:
            if stop_requested(Path(args.stop_file), token):
                server.should_exit = True
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
        return 0 if server.started else 1
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--stop-timeout", type=int, default=120)
    return asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
