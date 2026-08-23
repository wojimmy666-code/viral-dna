from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_items(values: list[str]) -> list[str]:
    normalized = [_normalize_text(value) for value in values]
    return list(dict.fromkeys(value for value in normalized if value))


class CategoryProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)
    category_name: str = Field(min_length=1, max_length=80)
    brand_name: str | None = Field(default=None, max_length=120)
    brief: str = Field(min_length=1, max_length=240)
    audiences: list[str] = Field(default_factory=list, min_length=1, max_length=12)
    selling_points: list[str] = Field(default_factory=list, min_length=1, max_length=16)
    scenes: list[str] = Field(default_factory=list, max_length=16)
    forbidden_claims: list[str] = Field(default_factory=list, max_length=20)
    visual_style: str | None = Field(default=None, max_length=500)

    @field_validator("display_name", "category_name", "brief")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("brand_name", "visual_style")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_text(value) or None

    @field_validator("audiences", "selling_points", "scenes", "forbidden_claims")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_items(values)

    @model_validator(mode="after")
    def ensure_grounding_fields(self) -> Self:
        if not self.display_name or not self.category_name or not self.brief:
            raise ValueError("档案名称、所属品类和一句话定位不能为空")
        if not self.audiences:
            raise ValueError("目标人群不能为空")
        if not self.selling_points:
            raise ValueError("核心卖点不能为空")
        return self


class CategoryProfileCreate(CategoryProfileFields):
    pass


class CategoryProfileUpdate(CategoryProfileFields):
    revision: int = Field(ge=1)


class CategoryProfileRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)


class CategoryProfile(CategoryProfileFields):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    revision: int = Field(default=1, ge=1)
    usage_count: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = None


class CategoryProfileSnapshot(CategoryProfileFields):
    id: UUID
    account_id: UUID
    revision: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_profile(cls, profile: CategoryProfile) -> CategoryProfileSnapshot:
        field_names = set(CategoryProfileFields.model_fields)
        source = {
            "id": str(profile.id),
            "account_id": str(profile.account_id),
            "revision": profile.revision,
            **profile.model_dump(mode="json", include=field_names),
        }
        fingerprint = hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return cls(**source, fingerprint=fingerprint)


class CategoryProfileListResponse(BaseModel):
    items: list[CategoryProfile]
    total: int = Field(ge=0)


class CategoryProfileState(BaseModel):
    schema_version: int = 1
    profiles: list[CategoryProfile] = Field(default_factory=list)
