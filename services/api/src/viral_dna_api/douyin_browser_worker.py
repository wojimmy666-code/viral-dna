"""Private, owned browser worker. No stealth patches, CAPTCHA solver or shared profile.

Only sanitized state and final file metadata cross stdout. Cookie values, page HTML,
signed media URLs and browser errors never leave this process.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sys
import threading
import time
from contextlib import suppress
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx

from .douyin_extractor import DouyinPageIE
from .link_ingestion import LinkIngestionError, normalize_platform_url
from .media import MAX_VIDEO_SECONDS


def emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


def find_detail(value, video_id: str, depth: int = 0) -> dict | None:
    if depth > 16:
        return None
    if isinstance(value, dict):
        if str(value.get("aweme_id", value.get("awemeId", ""))) == video_id:
            if isinstance(value.get("video"), dict):
                return value
        for child in list(value.values())[:500]:
            found = find_detail(child, video_id, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for child in value[:100]:
            found = find_detail(child, video_id, depth + 1)
            if found:
                return found
    return None


def media_urls(detail: dict) -> list[str]:
    video = detail.get("video", {})
    addresses = [video.get("play_addr"), video.get("playAddr")]
    rates = video.get("bit_rate", video.get("bitRate", []))
    if isinstance(rates, list):
        for rate in sorted(
            (r for r in rates if isinstance(r, dict)),
            key=lambda r: float(r.get("bit_rate", r.get("bitRate", 0)) or 0),
            reverse=True,
        ):
            addresses.append(rate.get("play_addr", rate.get("playAddr")))
    result = []
    for address in addresses:
        urls = (
            address.get("url_list", address.get("urlList", [])) if isinstance(address, dict) else []
        )
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and DouyinPageIE._safe_media_url(url) and url not in result:
                    result.append(url)
    return result[:8]


def imported_cookies(path: Path) -> list[dict]:
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    result = []
    for cookie in jar:
        if cookie.expires and cookie.expires <= time.time():
            continue
        domain = cookie.domain.lstrip(".").lower()
        if domain not in {"douyin.com", "iesdouyin.com"} and not domain.endswith(
            (".douyin.com", ".iesdouyin.com")
        ):
            continue
        result.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path or "/",
                "secure": cookie.secure,
                "httpOnly": cookie.has_nonstandard_attr("HTTPOnly"),
                "expires": cookie.expires or -1,
            }
        )
    return result


async def visible_challenge(page) -> str | None:
    # A generic '登录' navigation button and HTTP 403 are NOT verification evidence.
    for frame in page.frames:
        for selector in (
            '[id*="captcha"]',
            '[class*="captcha"]',
            '[role="dialog"]',
            '[class*="login-modal"]',
            '[class*="loginModal"]',
        ):
            for element in (await frame.locator(selector).all())[:8]:
                if not await element.is_visible():
                    continue
                text = (await element.inner_text(timeout=1000))[:2000]
                if any(
                    word in text
                    for word in (
                        "拖动滑块",
                        "完成验证",
                        "安全验证",
                        "请依次点击",
                        "验证后继续",
                    )
                ):
                    return "verification"
                if any(
                    word in text
                    for word in (
                        "扫码登录",
                        "短信登录",
                        "登录后观看",
                        "登录后即可",
                        "验证码登录",
                    )
                ):
                    return "login"
    return None


async def seed_cookies(context, cookies: list[dict]) -> int:
    """One incompatible exported Cookie must not prevent interactive login."""
    if not cookies:
        return 0
    try:
        await context.add_cookies(cookies)
        return 0
    except Exception:
        rejected = 0
        for cookie in cookies:
            try:
                await context.add_cookies([cookie])
            except Exception:
                rejected += 1
        return rejected


async def download_media(context, page, detail: dict, target: Path, maximum: int) -> Path:
    urls = media_urls(detail)
    if not urls:
        raise LinkIngestionError("link_browser_media_missing", "页面未提供该视频的可下载媒体。")
    user_agent = await page.evaluate("navigator.userAgent")
    partial = target / f"browser-{uuid4().hex}.part"
    destination = target / "original.mp4"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            for initial in urls:
                current = initial
                for _ in range(4):
                    if not DouyinPageIE._safe_media_url(current):
                        raise LinkIngestionError("link_redirect_blocked", "视频下载跳转不受支持。")
                    # Browser-context cookies are scoped to THIS exact media URL, never
                    # copied wholesale to a CDN or exposed via the worker protocol.
                    cookies = await context.cookies([current])
                    headers = {
                        "User-Agent": user_agent,
                        "Referer": "https://www.douyin.com/",
                        "Accept": "*/*",
                        "Accept-Encoding": "identity",
                    }
                    if cookies:
                        headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    async with client.stream("GET", current, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            from urllib.parse import urljoin

                            current = urljoin(current, response.headers.get("location", ""))
                            continue
                        if response.status_code != 200:
                            break
                        length = response.headers.get("content-length", "0")
                        if length.isdigit() and int(length) > maximum:
                            raise LinkIngestionError(
                                "link_size_exceeded", "链接视频不能超过 500 MB"
                            )
                        total = 0
                        prefix = b""
                        with partial.open("wb") as output:
                            async for chunk in response.aiter_bytes(128 * 1024):
                                total += len(chunk)
                                if total > maximum:
                                    raise LinkIngestionError(
                                        "link_size_exceeded",
                                        "链接视频超过容量限制，已停止。",
                                    )
                                if len(prefix) < 32:
                                    prefix = (prefix + chunk)[:32]
                                output.write(chunk)
                        if total == 0 or b"ftyp" not in prefix:
                            break
                        partial.replace(destination)
                        return destination
        raise LinkIngestionError(
            "link_browser_download_denied",
            "浏览器读到了视频信息，但平台拒绝媒体下载；没有启动分析。",
            retryable=True,
        )
    finally:
        partial.unlink(missing_ok=True)


async def run(request: dict) -> dict:
    from playwright.async_api import async_playwright

    mode = request.get("mode", "download")
    source_url = normalize_platform_url(request["source_url"])
    if urlsplit(source_url).hostname not in {"www.douyin.com", "douyin.com", "v.douyin.com"}:
        raise LinkIngestionError("link_platform_unsupported", "本地浏览器目前只支持抖音。")
    video_match = re.search(r"/video/([0-9]+)", source_url)
    video_id = video_match.group(1) if video_match else None
    profile = Path(request["profile_dir"])
    await asyncio.to_thread(profile.mkdir, parents=True, exist_ok=True)
    commands: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def read_commands():
        for line in sys.stdin:
            try:
                command = json.loads(line).get("action", "")
                loop.call_soon_threadsafe(commands.put_nowait, command)
            except (ValueError, RuntimeError):
                continue
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(commands.put_nowait, "cancel")

    threading.Thread(target=read_commands, daemon=True).start()
    active_left = float(request.get("timeout_seconds", 120))
    human_left = float(request.get("human_timeout_seconds", 300))
    waiting = False
    detail = None
    response_tasks: set[asyncio.Task] = set()

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            channel=request.get("channel", "msedge"),
            headless=False,
            accept_downloads=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            chromium_sandbox=True,
            timeout=25000,
        )
        try:
            # Reseed only when the imported file changes; do not overwrite a newer
            # interactive login with the same old Cookie on every collection.
            seed_marker = profile / ".viraldna-cookie-seeded"
            cookie_path = request.get("cookie_file")
            fingerprint = (
                hashlib.sha256(await asyncio.to_thread(Path(cookie_path).read_bytes)).hexdigest()
                if cookie_path
                else None
            )
            previous_seed = seed_marker.read_text("ascii") if seed_marker.exists() else None
            rejected = 0
            if fingerprint and fingerprint != previous_seed:
                cookies = imported_cookies(Path(cookie_path))
                rejected = await seed_cookies(context, cookies)
                seed_marker.write_text(fingerprint, encoding="ascii")
            page = context.pages[0] if context.pages else await context.new_page()

            async def inspect_response(response):
                nonlocal detail
                parsed = urlsplit(response.url)
                if (
                    not video_id
                    or parsed.hostname != "www.douyin.com"
                    or "/aweme/" not in parsed.path
                    or response.status != 200
                ):
                    return
                try:
                    length = (await response.all_headers()).get("content-length", "0")
                    if length.isdigit() and int(length) > 4_000_000:
                        return
                    body = await response.body()
                    if len(body) <= 4_000_000:
                        detail = find_detail(json.loads(body), video_id) or detail
                except Exception:
                    return

            def on_response(response):
                task = asyncio.create_task(inspect_response(response))
                response_tasks.add(task)
                task.add_done_callback(response_tasks.discard)

            page.on("response", on_response)
            emit(
                {
                    "state": "reading",
                    "message": (
                        "部分 Cookie 不兼容，已跳过；正在通过专用浏览器读取视频。"
                        if rejected
                        else "专用浏览器已打开，正在读取视频。"
                    ),
                }
            )
            started = time.monotonic()
            try:
                await page.goto(source_url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                if page.is_closed():
                    raise LinkIngestionError(
                        "link_browser_closed", "采集浏览器已关闭。", retryable=True
                    ) from None
            previous = started
            while True:
                now = time.monotonic()
                if waiting:
                    human_left -= now - previous
                else:
                    active_left -= now - previous
                previous = now
                if human_left <= 0:
                    raise LinkIngestionError(
                        "link_verification_timeout",
                        "等待人工登录或验证超时，任务已停止。",
                        retryable=True,
                    )
                if active_left <= 0:
                    raise LinkIngestionError(
                        "link_browser_timeout",
                        "浏览器读取超时，未取得该视频；任务已停止。",
                        retryable=True,
                    )
                if page.is_closed():
                    raise LinkIngestionError(
                        "link_browser_closed", "采集窗口已关闭，任务已停止。", retryable=True
                    )
                while not commands.empty():
                    action = commands.get_nowait()
                    if action == "cancel":
                        raise LinkIngestionError(
                            "link_browser_cancelled", "已取消浏览器采集。", retryable=True
                        )
                    if action == "focus":
                        await page.bring_to_front()
                    if action == "continue" and mode == "connect":
                        return {"connected": True}
                    if action == "continue" and waiting:
                        # The user may have finished in another tab of this same
                        # dedicated browser. Refresh the original target only.
                        with suppress(Exception):
                            await page.reload(wait_until="domcontentloaded", timeout=10000)

                if not video_id and mode != "connect":
                    match = re.search(r"/video/([0-9]+)", normalize_platform_url(page.url))
                    if match:
                        video_id = match.group(1)
                        source_url = f"https://www.douyin.com/video/{video_id}"
                if video_id and detail is None:
                    # Public, rendered hydration data only; never eval page scripts.
                    for script in (await page.locator('script[type="application/json"]').all())[
                        :20
                    ]:
                        raw = await script.text_content(timeout=1000)
                        if raw and len(raw) < 4_000_000:
                            with suppress(ValueError):
                                detail = find_detail(json.loads(unquote(raw)), video_id) or detail
                challenge = await visible_challenge(page)
                should_wait = mode == "connect" or bool(challenge and detail is None)
                if should_wait != waiting:
                    waiting = should_wait
                    emit(
                        {
                            "state": "waiting_user" if waiting else "reading",
                            "reason": (challenge or "setup") if waiting else None,
                            "message": (
                                "请在专用窗口完成登录或验证，完成后会自动继续。"
                                if mode != "connect"
                                else "请在专用窗口登录抖音，然后点击「已完成登录」。"
                            )
                            if waiting
                            else "已继续读取原视频，无需重新提交分析。",
                            "human_seconds_left": max(0, math.ceil(human_left)),
                        }
                    )
                if mode != "connect" and detail is not None:
                    if mode == "probe":
                        if not media_urls(detail):
                            raise LinkIngestionError(
                                "link_browser_media_missing",
                                "该视频未提供可下载媒体。",
                            )
                        return {
                            "id": video_id,
                            "title": str(detail.get("desc", ""))[:500],
                            "webpage_url": source_url,
                        }
                    emit(
                        {"state": "downloading", "message": "已读取目标视频，正在下载并校验文件。"}
                    )
                    video = detail["video"]
                    duration = float(video.get("duration", 0) or 0) / 1000
                    if duration > MAX_VIDEO_SECONDS:
                        raise LinkIngestionError(
                            "link_duration_exceeded", "仅支持 2 分钟以内的视频。"
                        )
                    target = Path(request["target_dir"])
                    await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
                    async with asyncio.timeout(active_left):
                        path = await download_media(
                            context, page, detail, target, int(request["max_download_bytes"])
                        )
                        from .media import MediaProcessor

                        metadata = await MediaProcessor().probe(path)
                    if metadata.duration_seconds > MAX_VIDEO_SECONDS:
                        path.unlink(missing_ok=True)
                        raise LinkIngestionError(
                            "link_duration_exceeded", "仅支持 2 分钟以内的视频。"
                        )
                    return {
                        "id": video_id,
                        "filepath": str(path),
                        "webpage_url": source_url,
                        "title": str(detail.get("desc", ""))[:500],
                        "uploader": str((detail.get("author") or {}).get("nickname", ""))[:160],
                        "duration": metadata.duration_seconds,
                    }
                await asyncio.sleep(0.5)
        finally:
            for task in response_tasks:
                task.cancel()
            await asyncio.gather(*response_tasks, return_exceptions=True)
            await context.close()


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        result = asyncio.run(run(request))
        emit({"state": "completed", "info": result})
    except LinkIngestionError as exc:
        emit(
            {
                "state": "failed",
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                },
            }
        )
    except TimeoutError:
        emit(
            {
                "state": "failed",
                "error": {
                    "code": "link_browser_timeout",
                    "message": "浏览器采集超时，已停止。",
                    "retryable": True,
                },
            }
        )
    except Exception:
        emit(
            {
                "state": "failed",
                "error": {
                    "code": "link_browser_failed",
                    "message": "专用浏览器启动或读取失败，请检查浏览器安装和本机桌面会话。",
                    "retryable": True,
                },
            }
        )


if __name__ == "__main__":
    main()
