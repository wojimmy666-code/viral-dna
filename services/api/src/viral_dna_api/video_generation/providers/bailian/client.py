from __future__ import annotations

from typing import Any

import httpx


class BailianClient:
    def __init__(self, api_key: str, base_url: str, *, timeout_seconds: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds, connect=30),
        )

    async def __aenter__(self) -> BailianClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def create_task(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(
            f"{self.base_url}/services/aigc/video-generation/video-synthesis",
            headers={"X-DashScope-Async": "enable"},
            json=payload,
        )

    async def get_task(self, task_id: str) -> httpx.Response:
        return await self._client.get(f"{self.base_url}/tasks/{task_id}")

    async def cancel_task(self, task_id: str) -> httpx.Response:
        return await self._client.delete(f"{self.base_url}/tasks/{task_id}")
