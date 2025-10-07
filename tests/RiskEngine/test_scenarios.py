from __future__ import annotations

from QuantLib import Period

from RiskEngine.context import MarketContext
from RiskEngine.scenarios import Scenario, ScenarioInstruction


def test_equity_spot_shift_scenario() -> None:
    base_ctx = MarketContext.build_dummy()
    stress_ctx = base_ctx.copy()
    scenario = Scenario(
        name="equity_down",
        instructions=[ScenarioInstruction(target='equity_spot', key='OMX', shift=-0.05, relative=True)]
    )
    original = base_ctx.equity_spot['OMX'].currentLink().value()
    scenario.apply(base_ctx, stress_ctx)
    stressed = stress_ctx.equity_spot['OMX'].currentLink().value()
    assert stressed == original * 0.95
    # base_ctx remains unchanged
    assert base_ctx.equity_spot['OMX'].currentLink().value() == original


def test_discount_curve_shift_scenario() -> None:
    base_ctx = MarketContext.build_dummy()
    stress_ctx = base_ctx.copy()
    scenario = Scenario(
        name="rates_up",
        instructions=[ScenarioInstruction(target='discount', key='SEK', shift=0.01, relative=False)]
    )
    base_curve = base_ctx.discount['SEK'].currentLink()
    stress_curve = stress_ctx.discount['SEK'].currentLink()
    base_rate = base_curve.zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate()
    scenario.apply(base_ctx, stress_ctx)
    stressed_rate = stress_ctx.discount['SEK'].currentLink().zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate()
    assert stressed_rate == base_rate + 0.01
    # base_ctx remains unchanged
    assert base_ctx.discount['SEK'].currentLink().zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate() == base_rate


def test_composite_scenario() -> None:
    base_ctx = MarketContext.build_dummy()
    stress_ctx = base_ctx.copy()
    scenario = Scenario(
        name="rates_up_equity_down",
        instructions=[
            ScenarioInstruction(target='discount', key='SEK', shift=0.01, relative=False),
            ScenarioInstruction(target='equity_spot', key='OMX', shift=-0.05, relative=True),
        ]
    )
    base_curve = base_ctx.discount['SEK'].currentLink()
    base_rate = base_curve.zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate()
    base_equity = base_ctx.equity_spot['OMX'].currentLink().value()
    scenario.apply(base_ctx, stress_ctx)
    stressed_rate = stress_ctx.discount['SEK'].currentLink().zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate()
    stressed_equity = stress_ctx.equity_spot['OMX'].currentLink().value()
    assert stressed_rate == base_rate + 0.01
    assert stressed_equity == base_equity * 0.95
    # base_ctx remains unchanged
    assert base_ctx.discount['SEK'].currentLink().zeroRate(base_ctx.as_of + Period("1M"), base_curve.dayCounter(), 0, 1).rate() == base_rate
    assert base_ctx.equity_spot['OMX'].currentLink().value() == base_equity
