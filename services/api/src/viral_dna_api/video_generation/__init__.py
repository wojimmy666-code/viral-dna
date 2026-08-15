from .contracts import (
    VIDEO_ADAPTER_PROTOCOL_VERSION,
    VIDEO_PROMPT_VERSION,
    VIDEO_REQUEST_SCHEMA_VERSION,
    GeneratedVideo,
    OrderedReferenceFrame,
    OrderedReferenceVideo,
    VideoAdapterIdentity,
    VideoAdapterRequest,
    VideoAdapterResult,
    VideoGenerationAdapter,
    VideoGenerationError,
    VideoGenerationRequest,
)
from .gateway import VideoGenerationGateway, VideoGenerationGatewayError

__all__ = [
    "VIDEO_ADAPTER_PROTOCOL_VERSION",
    "VIDEO_PROMPT_VERSION",
    "VIDEO_REQUEST_SCHEMA_VERSION",
    "GeneratedVideo",
    "OrderedReferenceFrame",
    "OrderedReferenceVideo",
    "VideoAdapterIdentity",
    "VideoAdapterRequest",
    "VideoAdapterResult",
    "VideoGenerationAdapter",
    "VideoGenerationError",
    "VideoGenerationGateway",
    "VideoGenerationGatewayError",
    "VideoGenerationRequest",
]
