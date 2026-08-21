from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    key: str
    label: str
    link_domains: tuple[str, ...]
    cookie_domains: tuple[str, ...]

    @property
    def default_record_name(self) -> str:
        return f"{self.label}链接视频"


PLATFORM_SPECS = (
    PlatformSpec(
        key="douyin",
        label="抖音",
        link_domains=("douyin.com", "iesdouyin.com"),
        cookie_domains=("douyin.com", "iesdouyin.com"),
    ),
    PlatformSpec(
        key="xiaohongshu",
        label="小红书",
        link_domains=("xiaohongshu.com", "xhslink.com", "rednote.com"),
        cookie_domains=("xiaohongshu.com", "xhslink.com", "xhscdn.com", "rednote.com"),
    ),
    PlatformSpec(
        key="tiktok",
        label="TikTok",
        link_domains=("tiktok.com",),
        cookie_domains=("tiktok.com",),
    ),
    PlatformSpec(
        key="instagram",
        label="Instagram",
        link_domains=("instagram.com", "instagr.am"),
        cookie_domains=("instagram.com", "instagr.am"),
    ),
)

PLATFORM_SPECS_BY_KEY = {spec.key: spec for spec in PLATFORM_SPECS}
SUPPORTED_PLATFORM_LABELS = tuple(spec.label for spec in PLATFORM_SPECS)
SUPPORTED_PLATFORM_TEXT = "、".join(SUPPORTED_PLATFORM_LABELS)
DEFAULT_LINK_RECORD_NAMES = frozenset(spec.default_record_name for spec in PLATFORM_SPECS)


def platform_key(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)


def get_platform_spec(value: Any) -> PlatformSpec:
    return PLATFORM_SPECS_BY_KEY[platform_key(value)]


def platform_label(value: Any) -> str:
    return get_platform_spec(value).label


def default_link_record_name(value: Any) -> str:
    return get_platform_spec(value).default_record_name


def is_platform_source(value: Any) -> bool:
    return platform_key(value) in PLATFORM_SPECS_BY_KEY
