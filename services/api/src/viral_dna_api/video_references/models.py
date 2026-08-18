from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .domain import PersonReferencePolicy


class VideoReferencePlanStep(BaseModel):
    kind: Literal["identity", "appearance", "spatial_control", "transport"]
    label: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=120)
    status: Literal["ready", "optional", "blocked", "excluded"]
    detail: str = Field(default="", max_length=500)


class VideoReferenceStrategyResponse(BaseModel):
    model_alias: str
    model_label: str
    policy: PersonReferencePolicy
    strategy: Literal[
        "managed_actor_depth",
        "identity_image_depth",
        "image_text",
        "ordered_images",
        "person_free",
    ]
    title: str
    description: str
    managed_identity_required: bool
    managed_identity_bound: bool
    generation_allowed: bool
    blocker_message: str | None = None
    route_id: str
    route_label: str
    support_level: Literal["verified", "experimental", "reserved"]
    identity_transport: str
    spatial_control_transport: str
    spatial_control_semantics: str
    identity_source: str
    spatial_control_source: str
    depth_control_supported: bool = False
    depth_control_required: bool = False
    show_depth_control_controls: bool = False
    selected_depth_control_count: int = Field(default=0, ge=0, le=1)
    requires_public_media_url: bool = False
    public_media_ready: bool = False
    provider_verified: bool = True
    warnings: list[str] = Field(default_factory=list)
    plan_steps: list[VideoReferencePlanStep] = Field(default_factory=list)
