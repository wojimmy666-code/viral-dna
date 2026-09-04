from __future__ import annotations

import asyncio
import io
import zipfile

import pytest

from viral_dna_api.platform_skills import (
    PlatformSkillCatalogService,
    PlatformSkillError,
)
from viral_dna_api.platform_skills.contracts import SkillVersionCreate


def test_seed_catalog_and_published_version_immutability(tmp_path) -> None:
    async def scenario() -> None:
        service = PlatformSkillCatalogService(tmp_path / "platform-skills.json")
        catalog = await service.list_catalog()

        assert catalog.total == 3
        assert all(item.current_version.status == "published" for item in catalog.items)
        assert {item.slug for item in catalog.items} == {
            "cinematic-product-story",
            "creator-explainer",
            "rhythmic-sports-short",
        }

        source = catalog.items[0].current_version.manifest
        next_manifest = source.model_copy(
            update={
                "metadata": source.metadata.model_copy(update={"version": "1.1.0"}),
            }
        )
        draft = await service.create_version(
            SkillVersionCreate(manifest=next_manifest, changelog="test version")
        )
        assert draft.status == "draft"
        assert (await service.validate_version(draft.id)).valid

        published = await service.publish(draft.id, None)
        assert published.status == "published"
        current = await service.get_catalog_item(catalog.items[0].slug)
        assert current.current_version.id == published.id

        with pytest.raises(PlatformSkillError) as immutable:
            await service.update_draft(
                published.id,
                SkillVersionCreate(manifest=next_manifest, changelog="mutate"),
            )
        assert immutable.value.code == "published_skill_immutable"

    asyncio.run(scenario())


def test_skill_package_rejects_path_traversal(tmp_path) -> None:
    async def scenario() -> None:
        service = PlatformSkillCatalogService(tmp_path / "platform-skills.json")
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../escape.txt", "unsafe")
            archive.writestr("skill.yaml", "api_version: viraldna.video-skill/v1")

        with pytest.raises(PlatformSkillError) as unsafe:
            await service.import_package(archive_bytes.getvalue())
        assert unsafe.value.code == "skill_package_path_invalid"

    asyncio.run(scenario())
