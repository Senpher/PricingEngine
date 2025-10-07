from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math

from .context import MarketContext
from .engine import RiskEngine
from .portfolio import Portfolio
from .scenarios import Scenario


@dataclass
class InitializeRiskEngine:
    """Compatibility wrapper used by :mod:`PortfolioEngine`."""

    context: MarketContext
    portfolio: Portfolio
    scenarios: Iterable[Scenario]

    def __post_init__(self) -> None:
        scenarios = list(self.scenarios)
        self.scenarios = scenarios
        self._engine = RiskEngine(context=self.context, portfolio=self.portfolio, scenarios=scenarios)

    def get_portfolio_var(self, confidence: float = 0.95) -> float:
        """Compute a simple historical-scenario VaR.

        The VaR is calculated from the distribution of scenario losses relative to
        the base scenario. The quantile is computed using the "round up" method
        that is common in regulatory reporting.
        """

        if not 0 < confidence <= 1:
            raise ValueError("confidence level must be in (0, 1]")

        results = self._engine.run_all()
        if len(results) <= 1:
            raise ValueError("At least one shock scenario is required to compute VaR")

        base = results[0]
        losses = sorted(base.total_pv - scenario.total_pv for scenario in results[1:])
        if not losses:
            raise ValueError("Scenario evaluation failed to produce any losses")

        index = max(0, math.ceil(confidence * len(losses)) - 1)
        return losses[index]

    @property
    def engine(self) -> RiskEngine:
        return self._engine
