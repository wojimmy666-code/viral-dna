from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ..models import ImageGenerationModelOption

DEFAULT_IMAGE_CATALOG_PATH = Path(__file__).with_name("image_model_catalog.toml")


class ImageModelCatalogError(RuntimeError):
    """Raised when the image model/cost catalog cannot be trusted."""


class ImageModelCatalog:
    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("VIRAL_DNA_IMAGE_MODEL_CATALOG", "").strip()
        selected = path or (Path(configured) if configured else DEFAULT_IMAGE_CATALOG_PATH)
        self.path = selected.resolve()
        try:
            with self.path.open("rb") as source:
                payload = tomllib.load(source)
            self.catalog_version = str(payload.get("catalog_version") or "").strip()
            self.pricing_version = str(payload.get("pricing_version") or "").strip()
            self.models = TypeAdapter(list[ImageGenerationModelOption]).validate_python(
                payload.get("models")
            )
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise ImageModelCatalogError(f"无法读取图片模型目录：{self.path}") from exc
        if not self.catalog_version or not self.pricing_version or not self.models:
            raise ImageModelCatalogError("图片模型目录缺少版本或模型")
        aliases = [item.alias for item in self.models]
        if len(aliases) != len(set(aliases)):
            raise ImageModelCatalogError("图片模型目录存在重复别名")
        if any(item.pricing_version != self.pricing_version for item in self.models):
            raise ImageModelCatalogError("图片价格快照版本与目录版本不一致")

    def option(self, alias: str) -> ImageGenerationModelOption:
        normalized = alias.strip()
        for item in self.models:
            if item.alias == normalized:
                return item
        raise ImageModelCatalogError(f"图片模型目录不存在别名：{normalized}")

    def options(self, provider: str | None = None) -> list[ImageGenerationModelOption]:
        if provider is None:
            return list(self.models)
        return [item for item in self.models if item.provider == provider]


def load_image_model_catalog(path: Path | None = None) -> ImageModelCatalog:
    return ImageModelCatalog(path)
