from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from viral_dna_api.workspace_catalog import (
    AccountContextService,
    default_account_catalog_path,
)

from .contracts import (
    CategoryProfile,
    CategoryProfileCreate,
    CategoryProfileListResponse,
    CategoryProfileSnapshot,
    CategoryProfileUpdate,
)
from .repository import (
    CategoryProfileRepository,
    CategoryProfileRepositoryConflict,
    CategoryProfileRepositoryNameConflict,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_category_profiles_path() -> Path:
    return default_account_catalog_path().with_name("category-profiles.json")


class CategoryProfileServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class CategoryProfileService:
    def __init__(
        self,
        account_context: AccountContextService,
        repository: CategoryProfileRepository | None = None,
    ) -> None:
        self.account_context = account_context
        self.repository = repository or CategoryProfileRepository(
            default_category_profiles_path()
        )

    async def list(
        self,
        *,
        include_deleted: bool = False,
        query: str | None = None,
    ) -> CategoryProfileListResponse:
        account = await self.account_context.current_account()
        items = await self.repository.list(account.id)
        needle = "".join((query or "").split()).casefold()
        items = [
            item
            for item in items
            if (include_deleted or item.deleted_at is None)
            and (
                not needle
                or needle
                in "".join(
                    [
                        item.display_name,
                        item.category_name,
                        item.brand_name or "",
                        item.brief,
                    ]
                ).casefold()
            )
        ]
        items.sort(
            key=lambda item: (
                item.deleted_at is not None,
                -(item.last_used_at or item.updated_at).timestamp(),
            )
        )
        return CategoryProfileListResponse(items=items, total=len(items))

    async def get(
        self,
        profile_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> CategoryProfile:
        account = await self.account_context.current_account()
        profile = await self.repository.get(account.id, profile_id)
        if profile is None or (profile.deleted_at is not None and not include_deleted):
            raise CategoryProfileServiceError(404, "category_profile_not_found", "品类档案不存在")
        return profile

    async def create(self, payload: CategoryProfileCreate) -> CategoryProfile:
        account = await self.account_context.current_account()
        await self._ensure_unique(account.id, payload.display_name)
        return await self._save(
            CategoryProfile(account_id=account.id, **payload.model_dump())
        )

    async def update(
        self,
        profile_id: UUID,
        payload: CategoryProfileUpdate,
    ) -> CategoryProfile:
        current = await self.get(profile_id)
        self._ensure_revision(current, payload.revision)
        await self._ensure_unique(
            current.account_id,
            payload.display_name,
            exclude_id=current.id,
        )
        now = utc_now()
        return await self._save(
            current.model_copy(
                update={
                    **payload.model_dump(exclude={"revision"}),
                    "revision": current.revision + 1,
                    "updated_at": now,
                }
            ),
            expected_revision=current.revision,
        )

    async def delete(self, profile_id: UUID, revision: int) -> CategoryProfile:
        current = await self.get(profile_id)
        self._ensure_revision(current, revision)
        now = utc_now()
        return await self._save(
            current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "updated_at": now,
                    "deleted_at": now,
                }
            ),
            expected_revision=current.revision,
        )

    async def restore(self, profile_id: UUID, revision: int) -> CategoryProfile:
        current = await self.get(profile_id, include_deleted=True)
        self._ensure_revision(current, revision)
        if current.deleted_at is None:
            return current
        await self._ensure_unique(
            current.account_id,
            current.display_name,
            exclude_id=current.id,
        )
        return await self._save(
            current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "updated_at": utc_now(),
                    "deleted_at": None,
                }
            ),
            expected_revision=current.revision,
        )

    async def snapshot(self, profile_id: UUID) -> CategoryProfileSnapshot:
        return CategoryProfileSnapshot.from_profile(await self.get(profile_id))

    async def mark_used(self, profile_id: UUID) -> None:
        current = await self.get(profile_id)
        try:
            await self._save(
                current.model_copy(
                    update={
                        "usage_count": current.usage_count + 1,
                        "last_used_at": utc_now(),
                    }
                ),
                expected_revision=current.revision,
            )
        except CategoryProfileServiceError:
            # Usage telemetry must never invalidate an already persisted concept set.
            return

    async def _save(
        self,
        profile: CategoryProfile,
        *,
        expected_revision: int | None = None,
    ) -> CategoryProfile:
        try:
            return await self.repository.save(
                profile,
                expected_revision=expected_revision,
            )
        except CategoryProfileRepositoryConflict as exc:
            raise CategoryProfileServiceError(
                409,
                "category_profile_revision_conflict",
                "品类档案已在其他页面更新，请刷新后重试",
            ) from exc
        except CategoryProfileRepositoryNameConflict as exc:
            raise CategoryProfileServiceError(
                409,
                "category_profile_name_conflict",
                "同名品类档案已存在",
            ) from exc

    async def _ensure_unique(
        self,
        account_id: UUID,
        display_name: str,
        *,
        exclude_id: UUID | None = None,
    ) -> None:
        normalized = "".join(display_name.split()).casefold()
        items = await self.repository.list(account_id)
        if any(
            item.deleted_at is None
            and item.id != exclude_id
            and "".join(item.display_name.split()).casefold() == normalized
            for item in items
        ):
            raise CategoryProfileServiceError(
                409,
                "category_profile_name_conflict",
                "同名品类档案已存在",
            )

    @staticmethod
    def _ensure_revision(profile: CategoryProfile, revision: int) -> None:
        if profile.revision != revision:
            raise CategoryProfileServiceError(
                409,
                "category_profile_revision_conflict",
                "品类档案已在其他页面更新，请刷新后重试",
            )
