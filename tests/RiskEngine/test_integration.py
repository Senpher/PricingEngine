from __future__ import annotations

import copy

import pytest
from QuantLib import Date, Option, Period, TARGET, Actual365Fixed

from PricingEngine.Instruments.equity_option import EuropeanVanillaOption
from PricingEngine.Instruments.fx_forward import FxForward
from PricingEngine.Instruments.interest_rate_swap import InterestRateSwap, FixedLeg
from RiskEngine.context import MarketContext
from RiskEngine.engine import RiskEngine
from RiskEngine.portfolio import Portfolio, Position
from RiskEngine.scenarios import Scenario, ScenarioInstruction


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
    option = EuropeanVanillaOption(
        spot=context.equity_spot["OMX"],
        risk_free_curve=context.discount["SEK"],
        dividend_curve=context.dividend["OMX"],
        vol=context.vols["OMX_ATM"],
        maturity=maturity,
        strike=2400.0,
        option_type=Option.Call,
        quantity=5,
        contract_size=10,
    )
    fx_fwd_pts_curve = [
        {"tenor": tenor, "points": context.fx_fwd_points[("SEK", "USD")][tenor].value()}
        for tenor in context.fx_fwd_points[("SEK", "USD")]
    ]
    fx_forward = FxForward(
        nominal=1_000_000,
        forward_price=10.3,
        maturity=swap_dates[-1],
        base_currency="SEK",
        price_currency="USD",
        spot=context.fx_spot[("SEK", "USD")],
        discount_domestic=context.discount["USD"],
        fx_fwd_pts_curve=fx_fwd_pts_curve,
    )
    paying_leg = FixedLeg(
        nominal=5_000_000,
        currency="SEK",
        issue_date=swap_dates[0],
        maturity=swap_dates[-1],
        tenor=Period("6M"),
        calendar=TARGET(),
        day_counter=Actual365Fixed(),
        rate=0.021,
    )
    receiving_leg = FixedLeg(
        nominal=5_000_000,
        currency="SEK",
        issue_date=swap_dates[0],
        maturity=swap_dates[-1],
        tenor=Period("6M"),
        calendar=TARGET(),
        day_counter=Actual365Fixed(),
        rate=0.0,
    )
    ir_swap = InterestRateSwap(
        paying_leg=paying_leg,
        receiving_leg=receiving_leg,
        discount_curve=context.discount["SEK"]
    )
    return Portfolio(
        [
            Position("OMX_CALL", option),
            Position("USDSEK_FWD", fx_forward),
            Position("SEK_SWAP", ir_swap),
        ]
    )


@pytest.fixture()
def scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="rates_up_25bp",
            instructions=[ScenarioInstruction(target="discount", key="SEK", shift=0.0025, relative=False)],
        ),
        Scenario(
            name="vol_up",
            instructions=[ScenarioInstruction(target="vols", key="OMX_ATM", shift=0.05, relative=True)],
        ),
        Scenario(
            name="usdsek_up_2pct",
            instructions=[ScenarioInstruction(target="fx_spot", key=("SEK", "USD"), shift=0.02, relative=True)],
        ),
    ]


def test_risk_engine_matches_manual_revaluation(
    context: MarketContext, portfolio: Portfolio, scenarios: list[Scenario]
) -> None:
    engine = RiskEngine(context=context, portfolio=portfolio, scenarios=scenarios)
    results = engine.run_all()
    base_total = results[0].total_pv
    assert results[0].name == "Base"
    # Manual scenario application
    for scenario in scenarios:
        stress_ctx = copy.deepcopy(context)
        scenario.apply(context, stress_ctx)
        manual_total = portfolio.price(stress_ctx)
        scenario_result = next(r for r in results if r.name == scenario.name)
        assert scenario_result.total_pv == pytest.approx(manual_total)
        assert scenario_result.delta_vs_base == pytest.approx(manual_total - base_total)
