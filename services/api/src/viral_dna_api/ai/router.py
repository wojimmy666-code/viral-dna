from __future__ import annotations

from collections.abc import Mapping

from ..models import ModelTargetSnapshot
from .contracts import ModelProviderUnavailable, StructuredModelProvider


class ModelRouter:
    def __init__(self, providers: Mapping[str, StructuredModelProvider] | None = None) -> None:
        self._providers = dict(providers or {})

    def provider_for(self, target: ModelTargetSnapshot) -> StructuredModelProvider:
        existing = self._providers.get(target.provider)
        if existing is not None:
            return existing
        if target.provider == "dashscope":
            from .providers.dashscope import DashScopeProvider

            provider = DashScopeProvider()
            self._providers[target.provider] = provider
            return provider
        raise ModelProviderUnavailable(f"尚未实现模型 Provider：{target.provider}")
