from __future__ import annotations

from typing import Any

import httpx


class MiniMaxClient:
    def __init__(self, api_key: str, base_url: str, *, timeout_seconds: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_root = (
            self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url
        )
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds, connect=30),
        )

    async def __aenter__(self) -> MiniMaxClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def create_legacy_task(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(f"{self.base_url}/video_generation", json=payload)

    async def get_legacy_task(self, task_id: str) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}/query/video_generation",
            params={"task_id": task_id},
        )

    async def create_h3_task(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(f"{self.api_root}/v2/video_generation", json=payload)

    async def get_h3_task(self, task_id: str) -> httpx.Response:
        return await self._client.get(f"{self.api_root}/v2/query/video_generation/{task_id}")

    async def cancel_h3_task(self, task_id: str) -> httpx.Response:
        return await self._client.delete(f"{self.api_root}/v2/video_generation/{task_id}")

    async def retrieve_file(self, file_id: str) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}/files/retrieve",
            params={"file_id": file_id},
        )

    async def list_models(self) -> httpx.Response:
        return await self._client.get(f"{self.base_url}/models")
