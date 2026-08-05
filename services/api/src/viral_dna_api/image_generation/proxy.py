from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class LocalProxyConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalProxyResolution:
    mode: str
    url: str | None
    source: str


def normalize_local_proxy_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise LocalProxyConfigurationError("代理地址不能为空")
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise LocalProxyConfigurationError("代理地址格式无效") from exc
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not parts.hostname
        or port is None
        or not 1 <= port <= 65535
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise LocalProxyConfigurationError(
            "代理仅支持不含账号密码的 HTTP/HTTPS 主机与端口",
        )
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urlunsplit((parts.scheme.lower(), f"{host}:{port}", "", "", ""))


def _proxy_from_windows_value(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    entries: dict[str, str] = {}
    bare: list[str] = []
    for item in raw.split(";"):
        part = item.strip()
        if not part:
            continue
        if "=" in part:
            key, proxy = part.split("=", 1)
            entries[key.strip().lower()] = proxy.strip()
        else:
            bare.append(part)
    candidate = entries.get("https") or entries.get("http") or (bare[0] if bare else "")
    if not candidate:
        return None
    try:
        return normalize_local_proxy_url(candidate)
    except LocalProxyConfigurationError:
        return None


def _windows_user_proxy() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
    except (OSError, TypeError, ValueError):
        return None
    return _proxy_from_windows_value(server) if enabled else None


def detect_system_proxy() -> LocalProxyResolution:
    windows_proxy = _windows_user_proxy()
    if windows_proxy:
        return LocalProxyResolution("system", windows_proxy, "windows_user_proxy")
    for name in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        value = os.getenv(name, "").strip()
        if not value:
            continue
        try:
            return LocalProxyResolution(
                "system",
                normalize_local_proxy_url(value),
                "environment",
            )
        except LocalProxyConfigurationError:
            continue
    return LocalProxyResolution("system", None, "none")


def resolve_local_proxy(mode: str, manual_url: str | None = None) -> LocalProxyResolution:
    if mode == "disabled":
        return LocalProxyResolution(mode, None, "disabled")
    if mode == "manual":
        if not (manual_url or "").strip():
            raise LocalProxyConfigurationError("手动代理模式必须填写代理地址")
        return LocalProxyResolution(
            mode,
            normalize_local_proxy_url(manual_url or ""),
            "manual",
        )
    if mode != "system":
        raise LocalProxyConfigurationError("本机代理模式无效")
    return detect_system_proxy()


def proxy_environment(proxy_url: str | None) -> dict[str, str]:
    if not proxy_url:
        return {}
    normalized = normalize_local_proxy_url(proxy_url)
    return {
        "HTTP_PROXY": normalized,
        "HTTPS_PROXY": normalized,
        "http_proxy": normalized,
        "https_proxy": normalized,
    }
