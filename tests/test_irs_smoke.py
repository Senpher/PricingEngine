import QuantLib as ql

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg
from pricingengine.indices.index_utils import make_forecast_index
from pricingengine.irs import InterestRateSwap
from pricingengine.termstructures.curve_nodes import CurveNodes


def _build_curves():
    asof = ql.Date(1, 1, 2020)
    ql.Settings.instance().evaluationDate = asof
    dc = ql.Actual365Fixed()
    disc = CurveNodes(
        asof=asof,
        dates=[asof + ql.Period(50, ql.Years)],
        quotes=[0.02],
        day_count=dc,
        quote_kind="flat",
        role="discounting",
    )
    fwd = CurveNodes(
        asof=asof,
        dates=[asof + ql.Period(50, ql.Years)],
        quotes=[0.025],
        day_count=dc,
        quote_kind="flat",
        role="forecasting",
    )
    return asof, dc, disc, fwd


def _build_swap(asof: ql.Date, dc: ql.DayCounter) -> InterestRateSwap:
    calendar = ql.TARGET()
    issue = asof
    maturity = calendar.advance(issue, ql.Period(5, ql.Years))
    fixed_schedule = ql.Schedule(
        issue,
        maturity,
        ql.Period(ql.Annual),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )
    float_schedule = ql.Schedule(
        issue,
        maturity,
        ql.Period(ql.Semiannual),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )
    notional = 1_000_000
    fixed_leg = FixedLeg(
        valuation_date=asof,
        issue_date=issue,
        maturity=maturity,
        currency="EUR",
        day_counter=dc,
        future_schedule=fixed_schedule,
        nominal=notional,
        rate=0.023,
    )
    float_leg = FloatingLeg(
        valuation_date=asof,
        issue_date=issue,
        maturity=maturity,
        currency="EUR",
        day_counter=dc,
        future_schedule=float_schedule,
        nominal=notional,
        spread=0.0,
    )
    return InterestRateSwap(paying_leg=fixed_leg, receiving_leg=float_leg)


def test_irs_smoke() -> None:
    asof, dc, disc_nodes, fwd_nodes = _build_curves()
    index = make_forecast_index("euribor6m", fwd_nodes)
    swap = _build_swap(asof, dc)

    mtm = swap.mtm(index, disc_nodes)
    assert isinstance(mtm, float)

    pv01 = swap.pv01(index, disc_nodes)
    assert abs(pv01) > 0

    assert (
        abs(
            swap.fixed_leg_bpv(index, disc_nodes)
            - swap.float_leg_bpv(index, disc_nodes)
        )
        < 1_000_000
    )

    bumped = disc_nodes.bump(1.0)
    mtm_bumped = swap.mtm(index, bumped)
    fd = mtm_bumped - mtm
    assert abs(fd - pv01) < 1e-2 * 1_000_000
