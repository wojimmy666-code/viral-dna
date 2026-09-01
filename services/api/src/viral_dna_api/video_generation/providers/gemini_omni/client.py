from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx


def _public_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or host in {"localhost", "localhost.localdomain"}
        or host.endswith((".localhost", ".local", ".internal", ".lan"))
    ):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return address.is_global


class GeminiOmniClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout_seconds: float = 180,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._base_host = (urlsplit(self.base_url).hostname or "").lower()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=30),
        )

    @property
    def auth_headers(self) -> dict[str, str]:
        headers = {"x-goog-api-key": self.api_key}
        if self._base_host != "generativelanguage.googleapis.com":
            # Google-compatible relays commonly accept either the native header or
            # Bearer authentication. Both carry the same configured relay key.
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _download_headers(self, host: str) -> dict[str, str]:
        if host == self._base_host:
            return self.auth_headers
        if host == "generativelanguage.googleapis.com":
            return {"x-goog-api-key": self.api_key}
        return {}

    async def __aenter__(self) -> GeminiOmniClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def get_model(self, model: str) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}/models/{quote(model, safe='')}",
            headers=self.auth_headers,
        )

    async def create_interaction(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(
            f"{self.base_url}/interactions",
            headers={**self.auth_headers, "Content-Type": "application/json"},
            json=payload,
        )

    async def get_interaction(self, interaction_id: str) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}/interactions/{quote(interaction_id, safe='')}",
            headers=self.auth_headers,
        )

    async def cancel_interaction(self, interaction_id: str) -> httpx.Response:
        return await self._client.post(
            f"{self.base_url}/interactions/{quote(interaction_id, safe='')}/cancel",
            headers=self.auth_headers,
        )

    async def download_generated_video(self, uri: str) -> httpx.Response:
        target = urljoin(f"{self.base_url}/", uri)
        for _ in range(4):
            if not _public_https_url(target):
                raise httpx.InvalidURL("Gemini returned an unsafe video URL")
            host = (urlsplit(target).hostname or "").lower()
            headers = self._download_headers(host)
            response = await self._client.get(
                target,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location", "").strip()
            if not location:
                return response
            target = urljoin(target, location)
        raise httpx.InvalidURL("Gemini video download redirected too many times")
