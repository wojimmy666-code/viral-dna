from __future__ import annotations

import pytest

from viral_dna_api.image_generation.proxy import (
    LocalProxyConfigurationError,
    _proxy_from_windows_value,
    normalize_local_proxy_url,
    proxy_environment,
    resolve_local_proxy,
)


def test_normalizes_supported_local_proxy_urls() -> None:
    assert normalize_local_proxy_url("127.0.0.1:10808") == (
        "http://127.0.0.1:10808"
    )
    assert normalize_local_proxy_url("HTTPS://Proxy.Example:8443/") == (
        "https://proxy.example:8443"
    )
    with pytest.raises(LocalProxyConfigurationError, match="账号密码"):
        normalize_local_proxy_url("http://user:secret@127.0.0.1:10808")
    with pytest.raises(LocalProxyConfigurationError, match="HTTP/HTTPS"):
        normalize_local_proxy_url("socks5://127.0.0.1:10808")


def test_reads_https_preference_from_windows_proxy_value() -> None:
    assert _proxy_from_windows_value("127.0.0.1:10808") == (
        "http://127.0.0.1:10808"
    )
    assert _proxy_from_windows_value(
        "http=127.0.0.1:8080;https=127.0.0.1:10808",
    ) == "http://127.0.0.1:10808"


def test_manual_proxy_builds_explicit_child_environment() -> None:
    resolution = resolve_local_proxy("manual", "127.0.0.1:10808")
    assert resolution.source == "manual"
    assert resolution.url == "http://127.0.0.1:10808"
    assert proxy_environment(resolution.url) == {
        "HTTP_PROXY": "http://127.0.0.1:10808",
        "HTTPS_PROXY": "http://127.0.0.1:10808",
        "http_proxy": "http://127.0.0.1:10808",
        "https_proxy": "http://127.0.0.1:10808",
    }


def test_disabled_proxy_never_injects_environment() -> None:
    resolution = resolve_local_proxy("disabled")
    assert resolution.url is None
    assert resolution.source == "disabled"
    assert proxy_environment(resolution.url) == {}
