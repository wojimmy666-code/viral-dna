from __future__ import annotations

import json
import os
import platform as system_platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from yt_dlp import YoutubeDL

from .cookies import cookie_domain_matches
from .models import (
    BrowserDiscoveryResponse,
    BrowserInstallSummary,
    BrowserProfileSummary,
    CookieJarMetadata,
    PlatformKind,
    SupportedBrowser,
)


class BrowserCookieError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BrowserProfileLocation:
    browser: SupportedBrowser
    key: str
    label: str
    path: Path
    most_recent: bool = False


BROWSER_LABELS = {
    SupportedBrowser.CHROME: "Google Chrome",
    SupportedBrowser.EDGE: "Microsoft Edge",
    SupportedBrowser.FIREFOX: "Mozilla Firefox",
    SupportedBrowser.BRAVE: "Brave",
}


class BrowserProfileDetector:
    def discover(self) -> BrowserDiscoveryResponse:
        locations = self._locations()
        installs: list[BrowserInstallSummary] = []
        for browser in SupportedBrowser:
            profiles = [item for item in locations if item.browser == browser]
            root = self._browser_root(browser)
            installs.append(
                BrowserInstallSummary(
                    browser=browser,
                    label=BROWSER_LABELS[browser],
                    installed=bool(root and root.is_dir()),
                    profiles=[
                        BrowserProfileSummary(
                            key=item.key,
                            label=item.label,
                            most_recent=item.most_recent,
                        )
                        for item in profiles
                    ],
                )
            )
        return BrowserDiscoveryResponse(browsers=installs)

    def resolve_profile(
        self,
        browser: SupportedBrowser,
        profile_key: str,
    ) -> BrowserProfileLocation:
        for location in self._locations():
            if location.browser == browser and location.key == profile_key:
                return location
        raise BrowserCookieError(
            "platform_browser_profile_missing",
            "找不到所选浏览器用户配置，请重新检测",
        )

    def inspect_cookies(
        self,
        browser: SupportedBrowser,
        profile_key: str,
        platform: PlatformKind,
    ) -> CookieJarMetadata:
        location = self.resolve_profile(browser, profile_key)
        browser_spec = (browser.value, str(location.path), None, None)
        try:
            with YoutubeDL(
                {
                    "cookiesfrombrowser": browser_spec,
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                }
            ) as downloader:
                cookies = list(downloader.cookiejar)
        except Exception as exc:
            raise self._translate_read_error(exc) from exc

        now = datetime.now(UTC).timestamp()
        matching = [
            cookie
            for cookie in cookies
            if cookie_domain_matches(str(cookie.domain or ""), platform)
            and (cookie.expires is None or float(cookie.expires) > now)
        ]
        if not matching:
            raise BrowserCookieError(
                "platform_browser_cookie_missing",
                "该浏览器用户配置中没有找到当前平台的有效 Cookie，请先登录平台",
            )
        expiries = [float(cookie.expires) for cookie in matching if cookie.expires is not None]
        return CookieJarMetadata(
            cookie_count=len(matching),
            session_cookie_count=sum(cookie.expires is None for cookie in matching),
            earliest_expiry_at=(
                datetime.fromtimestamp(min(expiries), tz=UTC) if expiries else None
            ),
        )

    def browser_spec(
        self,
        browser: SupportedBrowser,
        profile_key: str,
    ) -> tuple[str, str, None, None]:
        location = self.resolve_profile(browser, profile_key)
        return browser.value, str(location.path), None, None

    def _locations(self) -> list[BrowserProfileLocation]:
        locations: list[BrowserProfileLocation] = []
        for browser in SupportedBrowser:
            root = self._browser_root(browser)
            if root is None or not root.is_dir():
                continue
            if browser == SupportedBrowser.FIREFOX:
                locations.extend(self._firefox_profiles(root))
            else:
                locations.extend(self._chromium_profiles(browser, root))
        return locations

    def _browser_root(self, browser: SupportedBrowser) -> Path | None:
        operating_system = system_platform.system().lower()
        home = Path.home()
        if operating_system == "windows":
            local = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
            roaming = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
            roots = {
                SupportedBrowser.CHROME: local / "Google" / "Chrome" / "User Data",
                SupportedBrowser.EDGE: local / "Microsoft" / "Edge" / "User Data",
                SupportedBrowser.BRAVE: local / "BraveSoftware" / "Brave-Browser" / "User Data",
                SupportedBrowser.FIREFOX: roaming / "Mozilla" / "Firefox" / "Profiles",
            }
            return roots[browser]
        if operating_system == "darwin":
            roots = {
                SupportedBrowser.CHROME: home / "Library/Application Support/Google/Chrome",
                SupportedBrowser.EDGE: home / "Library/Application Support/Microsoft Edge",
                SupportedBrowser.BRAVE: (
                    home / "Library/Application Support/BraveSoftware/Brave-Browser"
                ),
                SupportedBrowser.FIREFOX: home / "Library/Application Support/Firefox/Profiles",
            }
            return roots[browser]
        roots = {
            SupportedBrowser.CHROME: home / ".config/google-chrome",
            SupportedBrowser.EDGE: home / ".config/microsoft-edge",
            SupportedBrowser.BRAVE: home / ".config/BraveSoftware/Brave-Browser",
            SupportedBrowser.FIREFOX: home / ".mozilla/firefox",
        }
        return roots[browser]

    def _chromium_profiles(
        self,
        browser: SupportedBrowser,
        root: Path,
    ) -> list[BrowserProfileLocation]:
        candidates = [
            child
            for child in root.iterdir()
            if child.is_dir()
            and (child.name == "Default" or child.name.startswith("Profile "))
            and ((child / "Network" / "Cookies").is_file() or (child / "Cookies").is_file())
        ]
        newest = self._newest_profile(candidates)
        output: list[BrowserProfileLocation] = []
        for candidate in sorted(candidates, key=lambda item: item.name.casefold()):
            label = candidate.name
            preferences = candidate / "Preferences"
            if preferences.is_file():
                try:
                    payload = json.loads(preferences.read_text("utf-8-sig"))
                    label = str(payload.get("profile", {}).get("name") or candidate.name)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            output.append(
                BrowserProfileLocation(
                    browser=browser,
                    key=candidate.name,
                    label=label[:240],
                    path=candidate.resolve(),
                    most_recent=candidate == newest,
                )
            )
        return output

    def _firefox_profiles(self, root: Path) -> list[BrowserProfileLocation]:
        candidates = [
            child
            for child in root.iterdir()
            if child.is_dir() and (child / "cookies.sqlite").is_file()
        ]
        newest = self._newest_profile(candidates, cookie_name="cookies.sqlite")
        return [
            BrowserProfileLocation(
                browser=SupportedBrowser.FIREFOX,
                key=candidate.name,
                label=candidate.name.split(".", 1)[-1] or candidate.name,
                path=candidate.resolve(),
                most_recent=candidate == newest,
            )
            for candidate in sorted(candidates, key=lambda item: item.name.casefold())
        ]

    @staticmethod
    def _newest_profile(
        candidates: list[Path],
        *,
        cookie_name: str | None = None,
    ) -> Path | None:
        def modified(candidate: Path) -> float:
            paths = (
                [candidate / cookie_name]
                if cookie_name
                else [candidate / "Network" / "Cookies", candidate / "Cookies"]
            )
            try:
                return max((path.stat().st_mtime for path in paths if path.exists()), default=0)
            except OSError:
                return 0

        return max(candidates, key=modified, default=None)

    @staticmethod
    def _translate_read_error(error: Exception) -> BrowserCookieError:
        details = str(error).lower()
        if "could not copy" in details or "permission" in details or "being used" in details:
            return BrowserCookieError(
                "platform_browser_cookie_locked",
                "浏览器 Cookie 数据库正在被占用，请关闭浏览器后台进程后重试",
                retryable=True,
            )
        if any(marker in details for marker in ("decrypt", "dpapi", "app-bound", "app bound")):
            return BrowserCookieError(
                "platform_browser_cookie_decryption_failed",
                "浏览器安全保护阻止了 Cookie 解密，请改用 cookies.txt 导入",
            )
        if "could not find" in details or "not found" in details:
            return BrowserCookieError(
                "platform_browser_profile_missing",
                "找不到浏览器 Cookie 数据库，请重新检测用户配置",
            )
        return BrowserCookieError(
            "platform_browser_cookie_read_failed",
            "无法读取浏览器登录状态，请改用 cookies.txt 导入",
            retryable=True,
        )
