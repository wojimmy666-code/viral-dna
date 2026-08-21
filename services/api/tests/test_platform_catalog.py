from viral_dna_api.models import SourceType
from viral_dna_api.platform_catalog import (
    DEFAULT_LINK_RECORD_NAMES,
    PLATFORM_SPECS,
    default_link_record_name,
    get_platform_spec,
)
from viral_dna_api.platform_connections.models import PlatformKind


def test_platform_catalog_matches_source_and_connection_enums() -> None:
    catalog_keys = [spec.key for spec in PLATFORM_SPECS]

    assert catalog_keys == [item.value for item in SourceType if item != SourceType.UPLOAD]
    assert catalog_keys == [item.value for item in PlatformKind]
    assert len({domain for spec in PLATFORM_SPECS for domain in spec.link_domains}) == sum(
        len(spec.link_domains) for spec in PLATFORM_SPECS
    )


def test_platform_catalog_provides_labels_domains_and_default_names() -> None:
    assert get_platform_spec(SourceType.TIKTOK).label == "TikTok"
    assert "tiktok.com" in get_platform_spec(PlatformKind.TIKTOK).link_domains
    assert "instagram.com" in get_platform_spec(SourceType.INSTAGRAM).cookie_domains
    assert default_link_record_name(SourceType.INSTAGRAM) == "Instagram链接视频"
    assert default_link_record_name(SourceType.INSTAGRAM) in DEFAULT_LINK_RECORD_NAMES
