from __future__ import annotations

import math

import pytest
from QuantLib import Date, Option

from RiskEngine.context import MarketContext
from RiskEngine.engine import RiskEngine
from RiskEngine.instruments.equity_option import EuropeanVanillaOptionInstrument
from RiskEngine.instruments.fx_forward import FxForwardInstrument
from RiskEngine.instruments.interest_rate_swap import InterestRateSwapInstrument
from RiskEngine.portfolio import Portfolio, Position
from RiskEngine.risk_engine_interface import InitializeRiskEngine
from RiskEngine.scenarios import (
    CurveParallelShiftScenario,
    QuoteShiftScenario,
    Scenario,
    VolShiftScenario,
)


@pytest.fixture()
def context() -> MarketContext:
    return MarketContext.build_dummy()


@pytest.fixture()
def portfolio(context: MarketContext) -> Portfolio:
    maturity = Date(19, 11, 2025)
    swap_dates = (
        Date(2, 7, 2024),
        Date(2, 1, 2025),
        Date(2, 7, 2025),
    )
    option = EuropeanVanillaOptionInstrument(
        currency="SEK",
        spot=context.equity_spot["OMX"],
        risk_free_curve=context.discount["SEK"],
        dividend_curve=context.dividend["OMX"],
        vol_surface=context.vols["OMX_ATM"],
        maturity=maturity,
        strike=2400.0,
        option_type=Option.Call,
        quantity=5,
        contract_size=10,
    )
    fx_forward = FxForwardInstrument(
        currency="SEK",
        spot=context.fx_spot[("USD", "SEK")],
        domestic_curve=context.discount["SEK"],
        foreign_curve=context.discount["USD"],
        maturity=maturity,
        strike=10.30,
        notional=1_000_000,
    )
    ir_swap = InterestRateSwapInstrument(
        currency="SEK",
        discount_curve=context.discount["SEK"],
        payment_dates=swap_dates,
        fixed_rate=0.021,
        notional=5_000_000,
        spread=0.0,
    )
    return Portfolio(
        [
            Position("OMX_CALL", option),
            Position("USDSEK_FWD", fx_forward),
            Position("SEK_SWAP", ir_swap),
        ],
        base_currency="SEK",
    )


@pytest.fixture()
def scenarios() -> list[Scenario]:
    return [
        CurveParallelShiftScenario(name="rates_up_25bp", currency="SEK", shift=0.0025),
        VolShiftScenario(name="vol_up", code="OMX_ATM", shift=0.05, relative=True),
        QuoteShiftScenario(
            name="usdsek_up_2pct",
            accessor=lambda c: c.fx_spot_quotes[("USD", "SEK")],
            shift=0.02,
            relative=True,
        ),
    ]


def test_risk_engine_matches_manual_revaluation(
    context: MarketContext, portfolio: Portfolio, scenarios: list[Scenario]
) -> None:
    engine = RiskEngine(context=context, portfolio=portfolio, scenarios=scenarios)
    results = engine.run_all()

    with context.at_eval():
        base_valuation = portfolio.valuation()
    assert results[0].name == "Base"
    assert results[0].total_pv == pytest.approx(base_valuation.total(context.base_currency))

    base_total = results[0].total_pv

    for scenario in scenarios:
        scenario.apply(context)
        try:
            with context.at_eval():
                manual = portfolio.valuation()
        finally:
            scenario.undo(context)
        expected_total = manual.total(context.base_currency)
        scenario_result = next(r for r in results if r.name == scenario.name)
        assert scenario_result.total_pv == pytest.approx(expected_total)
        assert scenario_result.delta_vs_base == pytest.approx(expected_total - base_total)


def test_initialize_risk_engine_var(context: MarketContext, portfolio: Portfolio, scenarios: list[Scenario]) -> None:
    initializer = InitializeRiskEngine(context=context, portfolio=portfolio, scenarios=scenarios)
    var_95 = initializer.get_portfolio_var(confidence=0.95)

    engine_losses = []
    results = initializer.engine.run_all()
    base_total = results[0].total_pv
    for scenario_result in results[1:]:
        engine_losses.append(base_total - scenario_result.total_pv)

    engine_losses.sort()
    expected_index = max(0, math.ceil(0.95 * len(engine_losses)) - 1)
    expected_var = engine_losses[expected_index]
    assert var_95 == pytest.approx(expected_var)
