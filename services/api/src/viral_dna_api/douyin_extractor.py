"""Read public share-page data when Douyin's web-detail endpoint is incompatible.

No third-party parsing service, signature generator or verification solver is used.
Only metadata explicitly returned for the requested video may be consumed.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.utils import ExtractorError

SHARE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
MEDIA_DOMAINS = ("douyinvod.com", "douyin.com", "iesdouyin.com", "snssdk.com", "bytecdn.cn")


def share_video_detail(webpage: str, video_id: str) -> dict | None:
    """Parse JSON, never execute page scripts or accept a recommended/other video."""
    match = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", webpage)
    if not match:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(webpage[match.end():])
    except (ValueError, RecursionError):
        return None
    loaders = payload.get("loaderData") if isinstance(payload, dict) else None
    if not isinstance(loaders, dict):
        return None
    for route in loaders.values():
        if not isinstance(route, dict):
            continue
        result = route.get("videoInfoRes")
        items = result.get("item_list") if isinstance(result, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if (isinstance(item, dict) and str(item.get("aweme_id")) == video_id
                    and isinstance(item.get("video"), dict)):
                return item
    return None


class DouyinPageIE(DouyinIE):
    _VALID_URL = (
        r"https?://(?:www\.)?(?:douyin\.com/video/|iesdouyin\.com/share/video/)"
        r"(?P<id>[0-9]+)"
    )

    @classmethod
    def ie_key(cls):
        # Replace only Douyin, preserving yt-dlp's short-link and other extractors.
        return "Douyin"

    def _real_extract(self, url):
        video_id = self._match_id(url)
        try:
            return super()._real_extract(f"https://www.douyin.com/video/{video_id}")
        except ExtractorError as original:
            if "fresh cookies" not in str(original).lower():
                raise
            page = self._download_webpage(
                f"https://www.iesdouyin.com/share/video/{video_id}/", video_id,
                note="Reading public video share page", fatal=False,
                headers={"User-Agent": SHARE_USER_AGENT},
            )
            detail = share_video_detail(page or "", video_id)
            if detail is None:
                # Preserve the original transport cause; do not infer login failure
                # from a page containing only the application shell.
                raise original
        info = self._parse_aweme_video_app(detail)
        formats = info.get("formats") or []
        info["formats"] = [item for item in formats if self._safe_media_url(item.get("url"))]
        if not info["formats"]:
            raise ExtractorError("link_douyin_metadata_missing", expected=True)
        logger = self._downloader.params.get("logger")
        if logger is not None and hasattr(logger, "http_status"):
            logger.http_status = None
            logger.messages.clear()
        info["webpage_url"] = f"https://www.douyin.com/video/{video_id}"
        info["http_headers"] = {
            "Referer": "https://www.iesdouyin.com/", "User-Agent": SHARE_USER_AGENT,
        }
        return info

    @staticmethod
    def _safe_media_url(value):
        try:
            parsed = urlsplit(value or "")
            host = (parsed.hostname or "").lower()
            return (parsed.scheme in {"http", "https"} and not parsed.username
                    and not parsed.password and parsed.port in {None, 80, 443}
                    and any(host == domain or host.endswith(f".{domain}")
                            for domain in MEDIA_DOMAINS))
        except ValueError:
            return False
