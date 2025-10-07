from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .context import MarketContext
from .portfolio import Portfolio
from .scenarios import Scenario


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    total_pv: float
    delta_vs_base: float
    position_pvs: dict[str, float]
    totals_by_currency: dict[str, float]


class RiskEngine:
    """Coordinate the evaluation of a portfolio under multiple scenarios."""

    def __init__(
        self,
        *,
        context: MarketContext,
        portfolio: Portfolio,
        scenarios: Iterable[Scenario] | None = None,
        base_name: str = "Base",
    ) -> None:
        self.context = context
        self.portfolio = portfolio
        self.scenarios: list[Scenario] = list(scenarios or [])
        self.base_name = base_name

    def run_base(self) -> ScenarioResult:
        with self.context.at_eval():
            valuation = self.portfolio.valuation()
        total = valuation.total(self.context.base_currency)
        return ScenarioResult(
            name=self.base_name,
            total_pv=total,
            delta_vs_base=0.0,
            position_pvs=valuation.position_pvs,
            totals_by_currency=valuation.totals_by_currency,
        )

    def run_all(self) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        base_result = self.run_base()
        results.append(base_result)
        base_total = base_result.total_pv

        for scenario in self.scenarios:
            results.append(self._run_scenario(scenario, base_total))
        return results

    def _run_scenario(self, scenario: Scenario, base_total: float) -> ScenarioResult:
        with self.context.at_eval():
            scenario.apply(self.context)
            try:
                valuation = self.portfolio.valuation()
            finally:
                scenario.undo(self.context)
        total = valuation.total(self.context.base_currency)
        return ScenarioResult(
            name=scenario.name,
            total_pv=total,
            delta_vs_base=total - base_total,
            position_pvs=valuation.position_pvs,
            totals_by_currency=valuation.totals_by_currency,
        )

    def add_scenario(self, scenario: Scenario) -> None:
        self.scenarios.append(scenario)
