from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from viral_dna_api.main import app
from viral_dna_api.platform_connections.browser import (
    BrowserProfileDetector,
    BrowserProfileLocation,
)
from viral_dna_api.platform_connections.cookies import (
    CookieFileError,
    filter_netscape_cookie_file,
)
from viral_dna_api.platform_connections.models import (
    BrowserDiscoveryResponse,
    BrowserInstallSummary,
    BrowserProfileSummary,
    CookieJarMetadata,
    PlatformBrowserConnectionUpdate,
    PlatformKind,
    SupportedBrowser,
)
from viral_dna_api.platform_connections.repository import (
    InMemoryPlatformConnectionRepository,
)
from viral_dna_api.platform_connections.secret_store import (
    InMemoryPlatformSecretStore,
    WindowsDpapiSecretStore,
)
from viral_dna_api.platform_connections.service import PlatformConnectionService


def cookie_file(*rows: str) -> bytes:
    return ("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n").encode()


def cookie_row(domain: str, name: str, value: str, expiry: int = 0) -> str:
    return f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}"


class FakeAccountContext:
    def __init__(self) -> None:
        self.account_id = uuid4()
        self.device_id = uuid4()

    async def ensure_current(self):
        return SimpleNamespace(
            account=SimpleNamespace(id=self.account_id),
            device=SimpleNamespace(id=self.device_id, name="测试设备"),
        )


class FakeBrowserDetector:
    def discover(self) -> BrowserDiscoveryResponse:
        return BrowserDiscoveryResponse(
            browsers=[
                BrowserInstallSummary(
                    browser=SupportedBrowser.CHROME,
                    label="Google Chrome",
                    installed=True,
                    profiles=[
                        BrowserProfileSummary(key="Default", label="个人", most_recent=True)
                    ],
                )
            ]
        )

    def resolve_profile(self, browser: SupportedBrowser, profile_key: str):
        assert browser == SupportedBrowser.CHROME
        assert profile_key == "Default"
        return BrowserProfileLocation(
            browser=browser,
            key=profile_key,
            label="个人",
            path=Path("C:/browser/Default"),
            most_recent=True,
        )

    def inspect_cookies(self, browser, profile_key, platform):
        assert browser == SupportedBrowser.CHROME
        assert profile_key == "Default"
        assert platform == PlatformKind.DOUYIN
        return CookieJarMetadata(cookie_count=8, session_cookie_count=3)

    def browser_spec(self, browser, profile_key):
        self.resolve_profile(browser, profile_key)
        return browser.value, "C:/browser/Default", None, None


def test_cookie_filter_keeps_only_selected_platform_and_discards_expired_values() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    future = int((now + timedelta(days=2)).timestamp())
    expired = int((now - timedelta(days=2)).timestamp())
    payload = cookie_file(
        cookie_row(".douyin.com", "sessionid", "douyin-secret", future),
        cookie_row("#HttpOnly_.douyin.com", "sid", "http-only-secret", 0),
        cookie_row(".douyin.com", "old", "expired-secret", expired),
        cookie_row(".example.com", "other", "other-secret", future),
    )

    filtered, metadata = filter_netscape_cookie_file(
        payload,
        PlatformKind.DOUYIN,
        now=now,
    )

    text = filtered.decode()
    assert "douyin-secret" in text
    assert "http-only-secret" in text
    assert "expired-secret" not in text
    assert "other-secret" not in text
    assert metadata.cookie_count == 2
    assert metadata.session_cookie_count == 1


def test_cookie_filter_rejects_file_without_platform_cookies() -> None:
    payload = cookie_file(cookie_row(".example.com", "sid", "secret"))
    with pytest.raises(CookieFileError) as caught:
        filter_netscape_cookie_file(payload, PlatformKind.XIAOHONGSHU)
    assert caught.value.code == "platform_cookie_missing"


def test_browser_discovery_lists_chromium_profiles_without_reading_cookie_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "Local"
    profile = local_app_data / "Google" / "Chrome" / "User Data" / "Default"
    (profile / "Network").mkdir(parents=True)
    (profile / "Network" / "Cookies").write_bytes(b"not-opened-by-discovery")
    (profile / "Preferences").write_text(
        '{"profile":{"name":"工作账号"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(
        "viral_dna_api.platform_connections.browser.system_platform.system",
        lambda: "Windows",
    )

    response = BrowserProfileDetector().discover()

    chrome = next(item for item in response.browsers if item.browser == "chrome")
    assert chrome.installed is True
    assert [(item.key, item.label) for item in chrome.profiles] == [
        ("Default", "工作账号")
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
@pytest.mark.asyncio
async def test_windows_dpapi_store_round_trips_without_plaintext_on_disk(
    tmp_path: Path,
) -> None:
    store = WindowsDpapiSecretStore(tmp_path / "secrets")
    account_id = uuid4()
    device_id = uuid4()
    secret = cookie_file(cookie_row(".douyin.com", "sid", "dpapi-private-value"))

    await store.save(account_id, device_id, PlatformKind.DOUYIN, secret)
    stored_path = tmp_path / "secrets" / str(account_id) / str(device_id) / "douyin.dpapi"

    assert stored_path.is_file()
    assert b"dpapi-private-value" not in stored_path.read_bytes()
    assert await store.read(account_id, device_id, PlatformKind.DOUYIN) == secret

    await store.delete(account_id, device_id, PlatformKind.DOUYIN)
    assert not stored_path.exists()


@pytest.mark.asyncio
async def test_imported_connections_are_scoped_and_materialized_temporarily() -> None:
    context = FakeAccountContext()
    secret_store = InMemoryPlatformSecretStore()
    service = PlatformConnectionService(
        context,
        InMemoryPlatformConnectionRepository(),
        secret_store,
    )
    payload = cookie_file(cookie_row(".xiaohongshu.com", "a1", "private-value"))

    summary = await service.import_cookie_file(PlatformKind.XIAOHONGSHU, payload)

    assert summary.configured is True
    assert summary.cookie_count == 1
    assert summary.source == "netscape_file"
    assert "private-value" not in summary.model_dump_json()

    async with service.session_for(PlatformKind.XIAOHONGSHU) as session:
        assert session.configured is True
        assert session.cookie_file is not None
        materialized = session.cookie_file
        assert materialized.is_file()
        assert "private-value" in materialized.read_text("utf-8")
    assert not materialized.exists()


@pytest.mark.asyncio
async def test_legacy_file_is_split_by_platform_without_overwriting_connections(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "cookies.txt"
    legacy_path.write_bytes(
        cookie_file(
            cookie_row(".douyin.com", "dy", "douyin-value"),
            cookie_row(".xiaohongshu.com", "xhs", "xhs-value"),
            cookie_row(".example.com", "other", "other-value"),
        )
    )
    context = FakeAccountContext()
    secret_store = InMemoryPlatformSecretStore()
    service = PlatformConnectionService(
        context,
        InMemoryPlatformConnectionRepository(),
        secret_store,
        legacy_cookie_path=str(legacy_path),
    )

    response = await service.list_connections()

    assert [item.configured for item in response.items] == [True, True]
    assert all(item.legacy_imported for item in response.items)
    douyin_secret = await secret_store.read(
        context.account_id,
        context.device_id,
        PlatformKind.DOUYIN,
    )
    xhs_secret = await secret_store.read(
        context.account_id,
        context.device_id,
        PlatformKind.XIAOHONGSHU,
    )
    assert b"douyin-value" in douyin_secret and b"xhs-value" not in douyin_secret
    assert b"xhs-value" in xhs_secret and b"douyin-value" not in xhs_secret
    assert b"other-value" not in douyin_secret + xhs_secret


@pytest.mark.asyncio
async def test_browser_profile_configuration_requires_consent_and_stores_no_cookie_values() -> None:
    context = FakeAccountContext()
    service = PlatformConnectionService(
        context,
        InMemoryPlatformConnectionRepository(),
        InMemoryPlatformSecretStore(),
        FakeBrowserDetector(),
    )

    summary = await service.configure_browser(
        PlatformKind.DOUYIN,
        PlatformBrowserConnectionUpdate(
            browser=SupportedBrowser.CHROME,
            profile_key="Default",
            consent_confirmed=True,
        ),
    )

    assert summary.source == "browser_profile"
    assert summary.browser == "chrome"
    assert summary.browser_profile_label == "个人"
    assert summary.cookie_count == 8
    async with service.session_for(PlatformKind.DOUYIN) as session:
        assert session.cookies_from_browser == ("chrome", "C:/browser/Default", None, None)


def test_platform_connection_api_imports_independent_cookie_files() -> None:
    payload = cookie_file(cookie_row(".douyin.com", "sid", "api-private-value"))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/settings/platform-connections/douyin/cookies",
            files={"file": ("douyin.txt", payload, "text/plain")},
            data={"usage_strategy": "on_auth_required"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["platform"] == "douyin"
        assert "api-private-value" not in response.text

        listed = client.get("/api/v1/settings/platform-connections")
        assert listed.status_code == 200
        douyin = next(item for item in listed.json()["items"] if item["platform"] == "douyin")
        assert douyin["configured"] is True

        removed = client.delete("/api/v1/settings/platform-connections/douyin")
        assert removed.status_code == 200
