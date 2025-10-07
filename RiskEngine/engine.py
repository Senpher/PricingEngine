from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List

from .context import MarketContext
from .portfolio import Portfolio
from .scenarios import Scenario


@dataclass
class ScenarioResult:
    name: str
    total_pv: float
    delta_vs_base: float


class RiskEngine:
    def __init__(
        self, context: MarketContext, portfolio: Portfolio, scenarios: List[Scenario]
    ):
        self.context = context
        self.portfolio = portfolio
        self.scenarios = scenarios

    def run_all(self) -> List[ScenarioResult]:
        results = []
        base_pv = self.portfolio.price(self.context)
        results.append(ScenarioResult("Base", base_pv, 0.0))
        stress_ctx = copy.deepcopy(self.context)
        for sc in self.scenarios:
            sc.apply(self.context, stress_ctx)
            pv = self.portfolio.price(stress_ctx)
            results.append(ScenarioResult(sc.name, pv, pv - base_pv))
        return results
