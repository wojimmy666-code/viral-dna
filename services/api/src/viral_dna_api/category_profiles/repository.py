from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from .contracts import CategoryProfile, CategoryProfileState


class CategoryProfileRepositoryConflict(RuntimeError):
    pass


class CategoryProfileRepositoryNameConflict(RuntimeError):
    pass


class CategoryProfileRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = asyncio.Lock()

    async def list(self, account_id: UUID) -> list[CategoryProfile]:
        async with self._lock:
            state = await asyncio.to_thread(self._read)
            return [
                CategoryProfile.model_validate(item.model_dump(mode="json"))
                for item in state.profiles
                if item.account_id == account_id
            ]

    async def get(self, account_id: UUID, profile_id: UUID) -> CategoryProfile | None:
        items = await self.list(account_id)
        return next((item for item in items if item.id == profile_id), None)

    async def save(
        self,
        profile: CategoryProfile,
        *,
        expected_revision: int | None = None,
    ) -> CategoryProfile:
        async with self._lock:
            state = await asyncio.to_thread(self._read)
            index = next(
                (
                    index
                    for index, item in enumerate(state.profiles)
                    if item.account_id == profile.account_id and item.id == profile.id
                ),
                None,
            )
            current = state.profiles[index] if index is not None else None
            if expected_revision is not None and (
                current is None or current.revision != expected_revision
            ):
                raise CategoryProfileRepositoryConflict
            normalized_name = "".join(profile.display_name.split()).casefold()
            if profile.deleted_at is None and any(
                item.account_id == profile.account_id
                and item.id != profile.id
                and item.deleted_at is None
                and "".join(item.display_name.split()).casefold() == normalized_name
                for item in state.profiles
            ):
                raise CategoryProfileRepositoryNameConflict
            saved = CategoryProfile.model_validate(profile.model_dump(mode="json"))
            if index is None:
                state.profiles.append(saved)
            else:
                state.profiles[index] = saved
            await asyncio.to_thread(self._write, state)
            return CategoryProfile.model_validate(saved.model_dump(mode="json"))

    def _read(self) -> CategoryProfileState:
        if not self.path.is_file():
            return CategoryProfileState()
        try:
            return CategoryProfileState.model_validate_json(
                self.path.read_text("utf-8-sig")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return CategoryProfileState()

    def _write(self, state: CategoryProfileState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(state.model_dump_json(indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
