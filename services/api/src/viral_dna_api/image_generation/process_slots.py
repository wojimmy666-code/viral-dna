from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import BinaryIO


class ProcessSlotError(RuntimeError):
    """Raised when a cross-process generation slot cannot be prepared."""


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ProcessSlotLimiter:
    """Coordinates local image-tool concurrency across API worker processes."""

    def __init__(self, lock_root: Path, namespace: str = "image-generation") -> None:
        self.lock_root = lock_root
        self.namespace = namespace

    @asynccontextmanager
    async def acquire(
        self,
        slots: int,
        *,
        poll_interval_seconds: float = 0.1,
    ) -> AsyncIterator[int]:
        slot_count = max(1, int(slots))
        try:
            await asyncio.to_thread(self.lock_root.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise ProcessSlotError("无法创建本机生图并发锁目录") from exc

        handle: BinaryIO | None = None
        selected_slot = -1
        while handle is None:
            for index in range(slot_count):
                path = self.lock_root / f"{self.namespace}-{index:02d}.lock"
                try:
                    candidate = await asyncio.to_thread(path.open, "a+b")
                except OSError as exc:
                    raise ProcessSlotError("无法打开本机生图并发锁") from exc
                locked = await asyncio.to_thread(_try_lock, candidate)
                if locked:
                    handle = candidate
                    selected_slot = index
                    break
                candidate.close()
            if handle is None:
                await asyncio.sleep(max(0.02, poll_interval_seconds))

        try:
            yield selected_slot
        finally:
            try:
                await asyncio.to_thread(_unlock, handle)
            finally:
                handle.close()
