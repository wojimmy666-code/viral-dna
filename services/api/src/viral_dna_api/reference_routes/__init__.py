"""Model-specific routing for identity, motion, and visual references."""

from .domain import (
    IdentityReferenceTransport,
    MotionReferenceSemantics,
    MotionReferenceTransport,
    RouteSupportLevel,
    VideoReferenceRouteCapability,
    VideoReferenceRouteId,
)
from .resolver import ResolvedReferenceRoute, resolve_reference_route

__all__ = [
    "IdentityReferenceTransport",
    "MotionReferenceSemantics",
    "MotionReferenceTransport",
    "ResolvedReferenceRoute",
    "RouteSupportLevel",
    "VideoReferenceRouteCapability",
    "VideoReferenceRouteId",
    "resolve_reference_route",
]
