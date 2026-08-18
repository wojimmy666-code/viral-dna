from __future__ import annotations

from .contracts import DepthEngineAdapter, DepthEngineCapability


class DepthEngineRegistryError(RuntimeError):
    pass


class DepthEngineRegistry:
    def __init__(self, engines: list[DepthEngineAdapter]) -> None:
        self._engines = {engine.engine_id: engine for engine in engines}

    def get(self, engine_id: str) -> DepthEngineAdapter | None:
        return self._engines.get(engine_id)

    def require(self, engine_id: str) -> DepthEngineAdapter:
        engine = self.get(engine_id)
        if engine is None:
            raise DepthEngineRegistryError(f"未找到深度引擎：{engine_id}")
        return engine

    def capabilities(self) -> list[DepthEngineCapability]:
        return [engine.capability() for engine in self._engines.values()]

    def engine_ids(self) -> tuple[str, ...]:
        return tuple(self._engines)
