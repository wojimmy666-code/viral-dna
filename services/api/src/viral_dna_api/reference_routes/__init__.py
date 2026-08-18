"""Model-specific routing for identity, motion, and visual references."""

from .domain import (
    IdentityReferenceTransport,
    RouteSupportLevel,
    SpatialControlSemantics,
    SpatialControlTransport,
    VideoReferenceRouteCapability,
    VideoReferenceRouteId,
)
from .resolver import ResolvedReferenceRoute, resolve_reference_route

__all__ = [
    "IdentityReferenceTransport",
    "ResolvedReferenceRoute",
    "RouteSupportLevel",
    "SpatialControlSemantics",
    "SpatialControlTransport",
    "VideoReferenceRouteCapability",
    "VideoReferenceRouteId",
    "resolve_reference_route",
]
