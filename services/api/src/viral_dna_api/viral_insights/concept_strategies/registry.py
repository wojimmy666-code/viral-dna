from __future__ import annotations

from ..contracts import ViralStrategy
from .base import BaseConceptStrategyBuilder
from .differentiated import DifferentiatedStrategyBuilder
from .enhanced import EnhancedStrategyBuilder
from .faithful import FaithfulStrategyBuilder
from .proof import ProofStrategyBuilder
from .scenario import ScenarioStrategyBuilder

_BUILDERS: dict[ViralStrategy, BaseConceptStrategyBuilder] = {
    ViralStrategy.FAITHFUL: FaithfulStrategyBuilder(),
    ViralStrategy.SCENARIO: ScenarioStrategyBuilder(),
    ViralStrategy.PROOF: ProofStrategyBuilder(),
    ViralStrategy.DIFFERENTIATED: DifferentiatedStrategyBuilder(),
    ViralStrategy.ENHANCED: EnhancedStrategyBuilder(),
}


def get_strategy_builder(strategy: ViralStrategy) -> BaseConceptStrategyBuilder:
    return _BUILDERS[strategy]
