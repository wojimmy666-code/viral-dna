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


@pytest.mark.parametrize(
    ("platform", "selected_domain", "other_domain"),
    [
        (PlatformKind.TIKTOK, ".tiktok.com", ".instagram.com"),
        (PlatformKind.INSTAGRAM, ".instagram.com", ".tiktok.com"),
    ],
)
def test_cookie_filter_isolates_international_platforms(
    platform: PlatformKind,
    selected_domain: str,
    other_domain: str,
) -> None:
    payload = cookie_file(
        cookie_row(selected_domain, "selected", "selected-secret"),
        cookie_row(other_domain, "other", "other-secret"),
    )

    filtered, metadata = filter_netscape_cookie_file(payload, platform)

    text = filtered.decode()
    assert "selected-secret" in text
    assert "other-secret" not in text
    assert metadata.cookie_count == 1


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

    configured = {item.platform: item for item in response.items}
    assert list(configured) == list(PlatformKind)
    assert configured[PlatformKind.DOUYIN].configured is True
    assert configured[PlatformKind.XIAOHONGSHU].configured is True
    assert configured[PlatformKind.TIKTOK].configured is False
    assert configured[PlatformKind.INSTAGRAM].configured is False
    assert configured[PlatformKind.DOUYIN].legacy_imported is True
    assert configured[PlatformKind.XIAOHONGSHU].legacy_imported is True
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


@pytest.mark.asyncio
async def test_connection_validation_normalizes_douyin_modal_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeAccountContext()
    service = PlatformConnectionService(
        context,
        InMemoryPlatformConnectionRepository(),
        InMemoryPlatformSecretStore(),
    )
    await service.import_cookie_file(
        PlatformKind.DOUYIN,
        cookie_file(cookie_row(".douyin.com", "sid", "private-value")),
    )
    probed_urls: list[str] = []

    async def probe(url, _session):
        probed_urls.append(url)

    monkeypatch.setattr(
        service,
        "_probe_url",
        probe,
    )

    response = await service.validate(
        PlatformKind.DOUYIN,
        test_url=(
            "https://www.douyin.com/user/self?from_tab_name=main&"
            "modal_id=7665298660867001638&showTab=favorite_collection"
        ),
    )

    assert response.connection.health == "valid"
    assert probed_urls == ["https://www.douyin.com/video/7665298660867001638"]
    assert response.connection.last_tested_at is not None


@pytest.mark.asyncio
async def test_local_check_never_clears_network_failure_or_fakes_success():
    service = PlatformConnectionService(
        FakeAccountContext(), InMemoryPlatformConnectionRepository(), InMemoryPlatformSecretStore(),
    )
    imported = await service.import_cookie_file(
        PlatformKind.DOUYIN, cookie_file(cookie_row(".douyin.com", "sid", "private-value")),
    )
    assert imported.health == "ready"
    assert imported.last_checked_at is not None
    assert imported.last_tested_at is None and imported.last_success_at is None
    await service.report_failure(PlatformKind.DOUYIN, "link_access_denied", "平台拒绝访问")
    failed = (await service.list_connections()).items[0]
    response = await service.validate(PlatformKind.DOUYIN)
    assert response.network_tested is False
    assert response.connection.health == "error"
    assert response.connection.last_error_code == "link_access_denied"
    assert response.connection.last_tested_at == failed.last_tested_at
    assert response.connection.last_success_at is None
    await service.report_success(PlatformKind.DOUYIN)
    success = await service.validate(PlatformKind.DOUYIN)
    assert success.connection.health == "valid"
    assert success.connection.last_error_code is None


@pytest.mark.asyncio
async def test_network_probe_preserves_precise_error_and_cookie_cleanup(monkeypatch):
    from viral_dna_api.link_ingestion import LinkIngestionError
    from viral_dna_api.platform_connections.service import PlatformConnectionServiceError

    service = PlatformConnectionService(
        FakeAccountContext(), InMemoryPlatformConnectionRepository(), InMemoryPlatformSecretStore(),
    )
    await service.import_cookie_file(
        PlatformKind.DOUYIN, cookie_file(cookie_row(".douyin.com", "sid", "private-value")),
    )
    paths = []

    async def probe(url, session):
        paths.append(session.cookie_file)
        assert session.cookie_file.exists()
        raise LinkIngestionError("link_access_denied", "平台拒绝访问", retryable=True)

    monkeypatch.setattr(service, "_probe_url", probe)
    with pytest.raises(PlatformConnectionServiceError) as caught:
        await service.validate(PlatformKind.DOUYIN, test_url="https://www.douyin.com/video/123")
    assert caught.value.code == "link_access_denied"
    assert not paths[0].exists()
    summary = (await service.list_connections()).items[0]
    assert summary.health == "error" and summary.last_tested_at is not None
    assert summary.last_success_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["replace", "disconnect", "fail"])
async def test_stale_probe_cannot_overwrite_updated_or_disconnected_connection(
    monkeypatch, operation,
):
    from viral_dna_api.link_ingestion import LinkIngestionError
    from viral_dna_api.platform_connections.service import PlatformConnectionServiceError

    service = PlatformConnectionService(
        FakeAccountContext(), InMemoryPlatformConnectionRepository(), InMemoryPlatformSecretStore(),
    )
    content = cookie_file(cookie_row(".douyin.com", "sid", "private-value"))
    await service.import_cookie_file(PlatformKind.DOUYIN, content)

    async def probe(url, session):
        if operation == "disconnect":
            await service.disconnect(PlatformKind.DOUYIN)
        else:
            await service.import_cookie_file(PlatformKind.DOUYIN, content)
        if operation == "fail":
            raise LinkIngestionError("link_access_denied", "old connection failed")

    monkeypatch.setattr(service, "_probe_url", probe)
    with pytest.raises(PlatformConnectionServiceError):
        await service.validate(PlatformKind.DOUYIN, test_url="https://www.douyin.com/video/123")
    summary = (await service.list_connections()).items[0]
    assert summary.last_tested_at is None and summary.last_error_code is None
    assert summary.configured is (operation != "disconnect")


@pytest.mark.asyncio
async def test_wrong_platform_url_does_not_change_health():
    from viral_dna_api.platform_connections.service import PlatformConnectionServiceError

    service = PlatformConnectionService(
        FakeAccountContext(), InMemoryPlatformConnectionRepository(), InMemoryPlatformSecretStore(),
    )
    await service.import_cookie_file(
        PlatformKind.DOUYIN, cookie_file(cookie_row(".douyin.com", "sid", "private-value")),
    )
    with pytest.raises(PlatformConnectionServiceError) as caught:
        await service.validate(PlatformKind.DOUYIN, test_url="https://www.instagram.com/reel/123")
    assert caught.value.code == "platform_connection_test_url_mismatch"
    summary = (await service.list_connections()).items[0]
    assert summary.health == "ready" and summary.last_error_code is None


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
