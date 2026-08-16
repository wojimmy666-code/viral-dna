from __future__ import annotations

from pathlib import Path

import pytest

from viral_dna_api import public_media as public_media_module
from viral_dna_api.public_media import (
    PublicMediaStager,
    PublicMediaStagingError,
    normalize_public_media_base_url,
)
from viral_dna_api.workspace import WorkspaceManager


def _workspace(monkeypatch: pytest.MonkeyPatch, root: Path) -> WorkspaceManager:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("VIRAL_DNA_PUBLIC_MEDIA_BASE_URL", "https://media.example.test")
    monkeypatch.setenv("VIRAL_DNA_PUBLIC_MEDIA_TTL_SECONDS", "3600")
    return WorkspaceManager()


@pytest.mark.parametrize(
    "value",
    [
        "http://media.example.test",
        "https://localhost:4174",
        "https://127.0.0.1",
        "https://192.168.1.2",
        "https://user:pass@media.example.test",
    ],
)
def test_public_media_base_url_rejects_non_public_or_unsafe_values(value: str) -> None:
    with pytest.raises(PublicMediaStagingError):
        normalize_public_media_base_url(value)


def test_public_media_base_url_accepts_origin_or_api_base() -> None:
    assert normalize_public_media_base_url("https://media.example.test/") == (
        "https://media.example.test"
    )
    assert normalize_public_media_base_url("https://media.example.test/api/v1") == (
        "https://media.example.test"
    )


def test_staged_media_uses_a_signed_https_url_and_survives_service_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(monkeypatch, tmp_path / "workspace")
    source = workspace.root / "motion.mp4"
    source.write_bytes(b"motion-proxy")

    lease = PublicMediaStager(workspace).stage(source)
    token = lease.url.rsplit("/", 1)[-1]
    published = PublicMediaStager(workspace).resolve(token)

    assert lease.url.startswith(
        "https://media.example.test/api/v1/public-media/"
    )
    assert published.path.read_bytes() == b"motion-proxy"
    assert published.media_type == "video/mp4"
    assert published.expires_at == lease.expires_at


def test_public_media_token_rejects_tampering_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(monkeypatch, tmp_path / "workspace")
    source = workspace.root / "motion.mp4"
    source.write_bytes(b"motion-proxy")
    stager = PublicMediaStager(workspace)
    lease = stager.stage(source)
    token = lease.url.rsplit("/", 1)[-1]

    with pytest.raises(PublicMediaStagingError) as tampered:
        stager.resolve(f"{token[:-1]}x")
    assert tampered.value.code == "public_media_token_invalid"

    monkeypatch.setattr(
        public_media_module.time,
        "time",
        lambda: lease.expires_at + 1,
    )
    with pytest.raises(PublicMediaStagingError) as expired:
        stager.resolve(token)
    assert expired.value.code == "public_media_token_expired"
