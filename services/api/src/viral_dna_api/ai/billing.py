from __future__ import annotations

import os
import tomllib
from decimal import ROUND_CEILING, Decimal
from math import ceil
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from ..models import (
    AnalysisCostSummary,
    CostStatus,
    ModelCostBreakdown,
    ModelRun,
    ModelRunStatus,
    ModelUsage,
    PriceSnapshot,
)

DEFAULT_PRICING_PATH = Path(__file__).with_name("model_pricing.toml")
MICROS_PER_CNY = Decimal("1000000")


class PriceCatalogError(RuntimeError):
    """Raised when no trustworthy price snapshot can be selected."""


class PriceCatalog:
    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("VIRAL_DNA_MODEL_PRICING", "").strip()
        selected = path or (Path(configured) if configured else DEFAULT_PRICING_PATH)
        self.path = selected.resolve()
        try:
            with self.path.open("rb") as source:
                payload = tomllib.load(source)
            self.catalog_version = str(payload.get("catalog_version") or "").strip()
            if not self.catalog_version:
                raise PriceCatalogError("模型价格目录缺少 catalog_version")
            raw_prices = payload.get("prices")
            self.prices = TypeAdapter(list[PriceSnapshot]).validate_python(raw_prices)
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise PriceCatalogError(f"无法读取模型价格目录：{self.path}") from exc
        if not self.prices:
            raise PriceCatalogError("模型价格目录没有价格快照")
        if any(price.catalog_version != self.catalog_version for price in self.prices):
            raise PriceCatalogError("价格快照版本与价格目录 catalog_version 不一致")

    def snapshot_for(self, provider: str, model: str, input_tokens: int) -> PriceSnapshot:
        normalized_tokens = max(1, input_tokens)
        matches = [
            price
            for price in self.prices
            if price.provider == provider
            and price.model == model
            and price.input_tokens_above < normalized_tokens <= price.input_tokens_at_most
        ]
        if not matches:
            raise PriceCatalogError(
                f"模型 {provider}/{model} 没有覆盖 {input_tokens} 输入 Token 的价格快照"
            )
        return max(matches, key=lambda item: item.effective_from)


def cny_to_micros(value: Decimal) -> int:
    return int((value * MICROS_PER_CNY).quantize(Decimal("1"), rounding=ROUND_CEILING))


def micros_to_cny(value: int) -> Decimal:
    return (Decimal(value) / MICROS_PER_CNY).quantize(Decimal("0.000001"))


def calculate_cost_micros(usage: ModelUsage, price: PriceSnapshot) -> int:
    cached_tokens = min(usage.cached_input_tokens, usage.input_tokens)
    uncached_tokens = usage.input_tokens - cached_tokens
    cached_rate = price.cached_input_cny_per_million or price.input_cny_per_million
    # CNY / 1M tokens multiplied by 1M micros / CNY equals micros per token.
    total_micros = (
        Decimal(uncached_tokens) * price.input_cny_per_million
        + Decimal(cached_tokens) * cached_rate
        + Decimal(usage.output_tokens) * price.output_cny_per_million
    )
    return int(total_micros.quantize(Decimal("1"), rounding=ROUND_CEILING))


def estimate_text_tokens(text: str) -> int:
    # Conservative for Chinese-heavy prompts; provider usage remains authoritative.
    return max(1, len(text))


def estimate_visual_tokens(*, image_count: int, width: int = 640, height: int = 360) -> int:
    # Official Qwen visual estimate is h*w/(32*32)+2; ceil protects the budget cap.
    per_image = ceil((width * height) / (32 * 32)) + 2
    return max(0, image_count) * per_image


def committed_model_cost_micros(runs: list[ModelRun]) -> int:
    """Return charged cost plus conservative reservations for unfinished calls.

    Completed calls and failures with provider usage are reconciled to their
    measured cost. Running calls, and failures for which the provider supplied
    no usage, keep their estimate reserved. Cached and blocked ledger rows do
    not consume additional budget.
    """

    total = 0
    for run in runs:
        if run.status == ModelRunStatus.RUNNING:
            total += run.estimated_cost_micros
        elif run.status in {ModelRunStatus.COMPLETED, ModelRunStatus.FAILED}:
            total += (
                run.measured_cost_micros
                if run.usage.total_tokens > 0 or run.measured_cost_micros > 0
                else run.estimated_cost_micros
            )
    return total


def summarize_model_runs(
    analysis_id: UUID,
    runs: list[ModelRun],
    *,
    estimated_cost_micros: int = 0,
) -> AnalysisCostSummary:
    grouped: dict[tuple[str, str], ModelCostBreakdown] = {}
    for run in runs:
        key = (run.provider, run.resolved_model or run.requested_model)
        item = grouped.setdefault(
            key,
            ModelCostBreakdown(provider=key[0], model=key[1]),
        )
        item.run_count += 1
        item.measured_cost_micros += run.measured_cost_micros

    completed = sum(run.status == ModelRunStatus.COMPLETED for run in runs)
    failed = sum(run.status == ModelRunStatus.FAILED for run in runs)
    cached = sum(run.status == ModelRunStatus.CACHED for run in runs)
    status = (
        CostStatus.MEASURED
        if any(
            run.status
            in {
                ModelRunStatus.COMPLETED,
                ModelRunStatus.FAILED,
                ModelRunStatus.CACHED,
            }
            for run in runs
        )
        else CostStatus.ESTIMATED
    )
    total_estimated = max(estimated_cost_micros, committed_model_cost_micros(runs))
    return AnalysisCostSummary(
        analysis_id=analysis_id,
        status=status,
        estimated_cost_micros=total_estimated,
        measured_cost_micros=sum(run.measured_cost_micros for run in runs),
        run_count=len(runs),
        completed_run_count=completed,
        failed_run_count=failed,
        cached_run_count=cached,
        breakdown=sorted(grouped.values(), key=lambda item: (item.provider, item.model)),
    )
