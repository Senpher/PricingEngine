from __future__ import annotations

from RiskEngine.context import MarketContext
from RiskEngine.scenarios import (
    CompositeScenario,
    CurveParallelShiftScenario,
    QuoteShiftScenario,
    VolShiftScenario,
)


def test_quote_shift_scenario_applies_and_undoes() -> None:
    ctx = MarketContext.build_dummy()
    scenario = QuoteShiftScenario(
        name="fx_up",
        accessor=lambda c: c.fx_spot_quotes[("USD", "SEK")],
        shift=0.5,
        relative=False,
    )

    original = ctx.fx_spot_quotes[("USD", "SEK")].value()
    scenario.apply(ctx)
    assert ctx.fx_spot_quotes[("USD", "SEK")].value() == original + 0.5
    scenario.undo(ctx)
    assert ctx.fx_spot_quotes[("USD", "SEK")].value() == original


def test_curve_shift_scenario_changes_discount_rate() -> None:
    ctx = MarketContext.build_dummy()
    scenario = CurveParallelShiftScenario(name="rates_up", currency="SEK", shift=0.01)

    base_rate = ctx.discount_quotes["SEK"].value()
    scenario.apply(ctx)
    assert ctx.discount_quotes["SEK"].value() == base_rate + 0.01
    scenario.undo(ctx)
    assert ctx.discount_quotes["SEK"].value() == base_rate


def test_vol_shift_can_be_combined() -> None:
    ctx = MarketContext.build_dummy()
    vol_scn = VolShiftScenario(name="vol_up", code="OMX_ATM", shift=0.05, relative=True)
    curve_scn = CurveParallelShiftScenario(name="rates_down", currency="SEK", shift=-0.005)
    combo = CompositeScenario(name="combo", components=[vol_scn, curve_scn])

    base_vol = ctx.vol_quotes["OMX_ATM"].value()
    base_rate = ctx.discount_quotes["SEK"].value()

    combo.apply(ctx)
    assert ctx.vol_quotes["OMX_ATM"].value() == base_vol * 1.05
    assert ctx.discount_quotes["SEK"].value() == base_rate - 0.005

    combo.undo(ctx)
    assert ctx.vol_quotes["OMX_ATM"].value() == base_vol
    assert ctx.discount_quotes["SEK"].value() == base_rate
