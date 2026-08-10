from __future__ import annotations

from datetime import UTC, datetime

from .models import CookieJarMetadata, PlatformKind

MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024
NETSCAPE_HEADERS = {"# Netscape HTTP Cookie File", "# HTTP Cookie File"}
PLATFORM_COOKIE_DOMAINS = {
    PlatformKind.DOUYIN: ("douyin.com", "iesdouyin.com"),
    PlatformKind.XIAOHONGSHU: (
        "xiaohongshu.com",
        "xhslink.com",
        "xhscdn.com",
        "rednote.com",
    ),
}


class CookieFileError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def cookie_domain_matches(domain: str, platform: PlatformKind) -> bool:
    normalized = domain.removeprefix("#HttpOnly_").strip().lower().lstrip(".")
    return any(
        normalized == allowed or normalized.endswith(f".{allowed}")
        for allowed in PLATFORM_COOKIE_DOMAINS[platform]
    )


def filter_netscape_cookie_file(
    payload: bytes,
    platform: PlatformKind,
    *,
    now: datetime | None = None,
) -> tuple[bytes, CookieJarMetadata]:
    if not payload:
        raise CookieFileError("platform_cookie_file_empty", "Cookie 文件为空")
    if len(payload) > MAX_COOKIE_FILE_BYTES:
        raise CookieFileError(
            "platform_cookie_file_too_large",
            "Cookie 文件不能超过 2 MB",
        )
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CookieFileError(
            "platform_cookie_file_encoding",
            "Cookie 文件必须使用 UTF-8 编码",
        ) from exc

    lines = text.splitlines()
    first_content = next((line.strip() for line in lines if line.strip()), "")
    if first_content not in NETSCAPE_HEADERS:
        raise CookieFileError(
            "platform_cookie_file_invalid",
            "请选择 Netscape 格式的 cookies.txt 文件",
        )

    timestamp = int((now or datetime.now(UTC)).timestamp())
    kept: list[str] = []
    expired_matches = 0
    session_count = 0
    expiries: list[int] = []
    malformed_rows = 0
    for raw_line in lines:
        line = raw_line.strip("\r\n")
        if not line or line in NETSCAPE_HEADERS:
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            malformed_rows += 1
            continue
        if not cookie_domain_matches(parts[0], platform):
            continue
        try:
            expiry = int(parts[4] or "0")
        except ValueError:
            malformed_rows += 1
            continue
        if expiry > 0 and expiry <= timestamp:
            expired_matches += 1
            continue
        if expiry <= 0:
            session_count += 1
        else:
            expiries.append(expiry)
        kept.append(line)

    if not kept:
        if expired_matches:
            raise CookieFileError(
                "platform_cookie_expired",
                "该平台 Cookie 已过期，请重新登录后导出",
            )
        if malformed_rows:
            raise CookieFileError(
                "platform_cookie_file_invalid",
                "Cookie 文件格式无效或缺少完整字段",
            )
        raise CookieFileError(
            "platform_cookie_missing",
            "文件中没有找到该平台的 Cookie",
        )

    earliest = datetime.fromtimestamp(min(expiries), tz=UTC) if expiries else None
    filtered = "# Netscape HTTP Cookie File\n" + "\n".join(kept) + "\n"
    return filtered.encode("utf-8"), CookieJarMetadata(
        cookie_count=len(kept),
        session_cookie_count=session_count,
        earliest_expiry_at=earliest,
    )
