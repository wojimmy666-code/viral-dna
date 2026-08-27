from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from ..models import (
    AnalysisProfile,
    ModelOption,
    ModelPlanSnapshot,
    ModelRouteSnapshot,
    ModelTargetSnapshot,
    ModelTask,
)
from ..runtime_config import get_config_value

DEFAULT_CATALOG_PATH = Path(__file__).with_name("model_catalog.toml")
DISABLED_PROVIDERS = {"", "disabled", "none", "off"}


class ModelCatalogError(RuntimeError):
    """Raised when the version-controlled model catalog is invalid."""


class _ModelDefinition(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    region: str = Field(default="cn-beijing", min_length=1, max_length=80)
    endpoint: str = Field(default="default", min_length=1, max_length=80)
    thinking: bool = False
    label: str = Field(default="模型", min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class ModelCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        try:
            with self.path.open("rb") as source:
                payload = tomllib.load(source)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ModelCatalogError(f"无法读取模型目录：{self.path}") from exc

        self.catalog_version = str(payload.get("catalog_version") or "").strip()
        self.pricing_version = str(payload.get("pricing_version") or "").strip()
        if not self.catalog_version or not self.pricing_version:
            raise ModelCatalogError("模型目录缺少 catalog_version 或 pricing_version")

        raw_models = payload.get("models")
        raw_routes = payload.get("routes")
        self.prompts = {
            str(key): str(value) for key, value in (payload.get("prompts") or {}).items()
        }
        self.schemas = {
            str(key): str(value) for key, value in (payload.get("schemas") or {}).items()
        }
        if not isinstance(raw_models, dict) or not isinstance(raw_routes, dict):
            raise ModelCatalogError("模型目录缺少 models 或 routes")

        try:
            self.models = {
                str(alias): _ModelDefinition.model_validate(definition)
                for alias, definition in raw_models.items()
            }
        except ValidationError as exc:
            raise ModelCatalogError(f"模型目录中的模型定义无效：{exc}") from exc
        self.routes = raw_routes

    def resolve(
        self,
        profile: AnalysisProfile,
        *,
        allowed_providers: set[str] | None = None,
        preferred_alias: str | None = None,
        preferred_aliases: Mapping[ModelTask | str, str] | None = None,
        fallback_enabled: bool = True,
    ) -> ModelPlanSnapshot:
        raw_profile = self.routes.get(profile.value)
        if not isinstance(raw_profile, dict):
            raise ModelCatalogError(f"模型目录未配置分析档位：{profile.value}")
        normalized_preferred_aliases = {
            ModelTask(task): alias
            for task, alias in (preferred_aliases or {}).items()
            if alias
        }
        aliases_to_validate = {
            *(normalized_preferred_aliases.values()),
            *([preferred_alias] if preferred_alias else []),
        }
        for alias in aliases_to_validate:
            preferred = self.models.get(alias)
            if preferred is None:
                raise ModelCatalogError(f"模型目录没有 GUI 选择的模型：{alias}")
            if allowed_providers and preferred.provider not in allowed_providers:
                raise ModelCatalogError(f"模型 {alias} 不属于已启用的 Provider")

        routes: list[ModelRouteSnapshot] = []
        for task in ModelTask:
            raw_aliases = raw_profile.get(task.value, [])
            if not isinstance(raw_aliases, list):
                raise ModelCatalogError(f"任务路由必须是模型别名列表：{task.value}")
            aliases = [str(alias) for alias in raw_aliases]
            task_preferred_alias = normalized_preferred_aliases.get(
                task,
                preferred_alias,
            )
            if task in normalized_preferred_aliases and not fallback_enabled:
                aliases = [task_preferred_alias]
            elif task_preferred_alias:
                aliases = [
                    task_preferred_alias,
                    *(alias for alias in aliases if alias != task_preferred_alias),
                ]

            targets: list[ModelTargetSnapshot] = []
            for alias in aliases:
                definition = self.models.get(alias)
                if definition is None:
                    raise ModelCatalogError(f"任务 {task.value} 引用了未知模型：{alias}")
                if allowed_providers and definition.provider not in allowed_providers:
                    continue
                prompt_version = self.prompts.get(task.value)
                schema_version = self.schemas.get(task.value)
                if not prompt_version or not schema_version:
                    raise ModelCatalogError(f"任务 {task.value} 缺少 Prompt 或 Schema 版本")
                targets.append(
                    ModelTargetSnapshot(
                        alias=alias,
                        provider=definition.provider,
                        model=definition.model,
                        region=definition.region,
                        endpoint=definition.endpoint,
                        thinking=definition.thinking,
                        prompt_version=prompt_version,
                        schema_version=schema_version,
                    )
                )
            if targets:
                routes.append(ModelRouteSnapshot(task=task, targets=targets))

        if not any(route.task == ModelTask.SHOT_FACTS for route in routes):
            raise ModelCatalogError("当前 Provider 配置没有可用的 shot_facts 路由")
        return ModelPlanSnapshot(
            profile=profile,
            catalog_version=self.catalog_version,
            pricing_version=self.pricing_version,
            routes=routes,
        )

    def model_options(self, provider: str | None = None) -> list[ModelOption]:
        return [
            ModelOption(
                alias=alias,
                provider=definition.provider,
                model=definition.model,
                label=definition.label,
                description=definition.description,
            )
            for alias, definition in self.models.items()
            if provider is None or definition.provider == provider
        ]

    def model_option(self, alias: str) -> ModelOption:
        definition = self.models.get(alias)
        if definition is None:
            raise ModelCatalogError(f"模型目录没有模型：{alias}")
        return ModelOption(
            alias=alias,
            provider=definition.provider,
            model=definition.model,
            label=definition.label,
            description=definition.description,
        )


def _catalog_path() -> Path:
    configured = get_config_value("VIRAL_DNA_MODEL_CATALOG", "").strip()
    return Path(configured) if configured else DEFAULT_CATALOG_PATH


def load_model_catalog() -> ModelCatalog:
    return ModelCatalog(_catalog_path())


def default_analysis_profile() -> AnalysisProfile:
    raw = get_config_value("VIRAL_DNA_MODEL_PROFILE", AnalysisProfile.BALANCED.value)
    try:
        return AnalysisProfile(raw.strip().lower())
    except ValueError as exc:
        choices = ", ".join(profile.value for profile in AnalysisProfile)
        raise ModelCatalogError(f"VIRAL_DNA_MODEL_PROFILE 必须是以下值之一：{choices}") from exc


def configured_model_providers() -> set[str]:
    raw = get_config_value("VIRAL_DNA_VLM_PROVIDER", "disabled")
    return {
        value.strip().lower()
        for value in raw.split(",")
        if value.strip().lower() not in DISABLED_PROVIDERS
    }


def configured_model_alias() -> str | None:
    raw = get_config_value("VIRAL_DNA_VLM_MODEL_ALIAS", "auto").strip()
    return None if raw.lower() in {"", "auto"} else raw


def load_model_plan(
    profile: AnalysisProfile,
    *,
    preferred_aliases: Mapping[ModelTask | str, str] | None = None,
    fallback_enabled: bool = True,
) -> ModelPlanSnapshot | None:
    providers = configured_model_providers()
    if not providers:
        return None
    return load_model_catalog().resolve(
        profile,
        allowed_providers=providers,
        preferred_alias=configured_model_alias(),
        preferred_aliases=preferred_aliases,
        fallback_enabled=fallback_enabled,
    )
