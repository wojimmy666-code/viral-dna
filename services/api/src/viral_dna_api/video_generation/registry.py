from __future__ import annotations

from collections.abc import Iterable

from .contracts import VideoProviderAdapter
from .providers.bailian import BailianVideoProvider
from .providers.minimax import MiniMaxVideoProvider
from .providers.seedance import SeedanceVideoProvider


class VideoProviderRegistryError(LookupError):
    pass


class VideoProviderRegistry:
    def __init__(self, providers: Iterable[VideoProviderAdapter] | None = None) -> None:
        configured = (
            list(providers)
            if providers is not None
            else [
                BailianVideoProvider(),
                SeedanceVideoProvider(),
                MiniMaxVideoProvider(),
            ]
        )
        self._providers = {item.provider_id: item for item in configured}

    def get(self, provider_id: str) -> VideoProviderAdapter:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise VideoProviderRegistryError(f"未注册视频 Provider：{provider_id}") from exc

    def ids(self) -> list[str]:
        return sorted(self._providers)
