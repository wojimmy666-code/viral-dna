from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.category_profiles.contracts import (
    CategoryProfileCreate,
    CategoryProfileUpdate,
)
from viral_dna_api.category_profiles.repository import CategoryProfileRepository
from viral_dna_api.category_profiles.routes import create_category_profile_router
from viral_dna_api.category_profiles.service import (
    CategoryProfileService,
    CategoryProfileServiceError,
)


class FakeAccountContext:
    def __init__(self, account_id=None) -> None:
        self.account = SimpleNamespace(id=account_id or uuid4())

    async def current_account(self):
        return self.account


def profile_create(name: str = "都市通勤女装") -> CategoryProfileCreate:
    return CategoryProfileCreate(
        display_name=name,
        category_name="女装",
        brand_name="森屿",
        brief="为通勤女性提供利落、易搭配的轻职场女装",
        audiences=["25–35 岁通勤女性"],
        selling_points=["显瘦但不紧绷", "面料抗皱"],
        scenes=["上班通勤"],
        forbidden_claims=["绝对显瘦"],
        visual_style="都市自然光与克制低饱和色",
    )


def test_category_profile_crud_soft_delete_restore_and_revision(tmp_path) -> None:
    async def scenario() -> None:
        repository = CategoryProfileRepository(tmp_path / "category-profiles.json")
        service = CategoryProfileService(FakeAccountContext(), repository)
        created = await service.create(profile_create())
        assert created.revision == 1
        assert (await service.list()).total == 1

        updated = await service.update(
            created.id,
            CategoryProfileUpdate(
                revision=created.revision,
                **profile_create().model_copy(
                    update={"selling_points": ["显瘦但不紧绷", "机洗后易打理"]}
                ).model_dump(),
            ),
        )
        assert updated.revision == 2
        assert updated.selling_points[-1] == "机洗后易打理"

        with pytest.raises(CategoryProfileServiceError) as conflict:
            await service.update(
                created.id,
                CategoryProfileUpdate(
                    revision=1,
                    **profile_create().model_dump(),
                ),
            )
        assert conflict.value.status_code == 409

        deleted = await service.delete(updated.id, updated.revision)
        assert deleted.deleted_at is not None
        assert (await service.list()).total == 0
        assert (await service.list(include_deleted=True)).total == 1

        restored = await service.restore(deleted.id, deleted.revision)
        assert restored.deleted_at is None
        assert restored.revision == 4
        assert (await service.list()).total == 1

    asyncio.run(scenario())


def test_category_profiles_are_account_isolated_and_snapshots_are_immutable(tmp_path) -> None:
    async def scenario() -> None:
        repository = CategoryProfileRepository(tmp_path / "category-profiles.json")
        first_service = CategoryProfileService(FakeAccountContext(), repository)
        second_service = CategoryProfileService(FakeAccountContext(), repository)
        created = await first_service.create(profile_create())
        snapshot = await first_service.snapshot(created.id)

        assert (await second_service.list()).total == 0
        with pytest.raises(CategoryProfileServiceError) as missing:
            await second_service.get(created.id)
        assert missing.value.status_code == 404

        updated = await first_service.update(
            created.id,
            CategoryProfileUpdate(
                revision=created.revision,
                **profile_create().model_copy(update={"brief": "更新后的定位"}).model_dump(),
            ),
        )
        next_snapshot = await first_service.snapshot(updated.id)
        assert snapshot.brief != next_snapshot.brief
        assert snapshot.fingerprint != next_snapshot.fingerprint
        assert snapshot.revision == 1

    asyncio.run(scenario())


def test_category_profile_routes_return_structured_conflicts(tmp_path) -> None:
    service = CategoryProfileService(
        FakeAccountContext(),
        CategoryProfileRepository(tmp_path / "category-profiles.json"),
    )
    app = FastAPI()
    app.include_router(create_category_profile_router(service), prefix="/api/v1")

    with TestClient(app) as client:
        created_response = client.post(
            "/api/v1/me/category-profiles",
            json=profile_create().model_dump(mode="json"),
        )
        assert created_response.status_code == 201
        created = created_response.json()

        update_payload = {
            **profile_create().model_dump(mode="json"),
            "revision": created["revision"],
        }
        update_response = client.put(
            f"/api/v1/me/category-profiles/{created['id']}",
            json=update_payload,
        )
        assert update_response.status_code == 200

        conflict_response = client.put(
            f"/api/v1/me/category-profiles/{created['id']}",
            json=update_payload,
        )
        assert conflict_response.status_code == 409
        assert conflict_response.json()["detail"]["code"] == "category_profile_revision_conflict"
