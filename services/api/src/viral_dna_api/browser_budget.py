"""A wall-clock deadline that excludes explicitly bounded human verification."""

from __future__ import annotations

import asyncio


class HumanPauseBudget:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self.remaining: float | None = None
        self.timer: asyncio.Timeout | None = None

    async def __aenter__(self):
        self.timer = asyncio.timeout(self.seconds)
        await self.timer.__aenter__()
        return self

    def waiting(self, value: bool) -> None:
        if self.timer is None or self.timer.expired():
            return
        now = asyncio.get_running_loop().time()
        if value and self.remaining is None:
            self.remaining = max(0, (self.timer.when() or now) - now)
            self.timer.reschedule(None)
        elif not value and self.remaining is not None:
            self.timer.reschedule(now + self.remaining)
            self.remaining = None

    async def __aexit__(self, *args):
        return await self.timer.__aexit__(*args)
