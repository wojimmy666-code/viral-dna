from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from viral_dna_api.image_generation.process_slots import ProcessSlotLimiter


@pytest.mark.asyncio
async def test_process_slot_limiter_serializes_independent_instances(
    tmp_path: Path,
) -> None:
    first = ProcessSlotLimiter(tmp_path / "locks")
    second = ProcessSlotLimiter(tmp_path / "locks")
    second_entered = asyncio.Event()

    async def wait_for_slot() -> None:
        async with second.acquire(1, poll_interval_seconds=0.02):
            second_entered.set()

    async with first.acquire(1):
        waiter = asyncio.create_task(wait_for_slot())
        await asyncio.sleep(0.1)
        assert second_entered.is_set() is False
    await asyncio.wait_for(waiter, timeout=2)
    assert second_entered.is_set() is True
