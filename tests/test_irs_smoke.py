import QuantLib as ql

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg
from pricingengine.indices.index_utils import make_forecast_index
from pricingengine.irs import InterestRateSwap
from pricingengine.termstructures.curve_nodes import CurveNodes


def _build_curves():
    as_of = ql.Date(1, 1, 2020)
    ql.Settings.instance().evaluationDate = as_of
    dc = ql.Actual365Fixed()
    disc = CurveNodes(
        as_of=as_of,
        dates=[as_of + ql.Period(50, ql.Years)],
        quotes=[0.02],
        day_counter=dc,
        quote_kind="flat",
        role="discounting",
    )
    fwd = CurveNodes(
        as_of=as_of,
        dates=[as_of + ql.Period(50, ql.Years)],
        quotes=[0.025],
        day_counter=dc,
        quote_kind="flat",
        role="forecasting",
    )
    return as_of, dc, disc, fwd


def _build_swap(as_of: ql.Date, dc: ql.DayCounter) -> InterestRateSwap:
    calendar = ql.TARGET()
    issue = as_of
    maturity = calendar.advance(issue, ql.Period(5, ql.Years))
    notional = 1_000_000
    fixed_leg = FixedLeg(
        valuation_date=as_of,
        nominal=notional,
        currency="EUR",
        issue_date=issue,
        maturity=maturity,
        tenor=ql.Period(ql.Annual),
        calendar=calendar,
        day_counter=dc,
        rate=0.023,
    )
    float_leg = FloatingLeg(
        valuation_date=as_of,
        nominal=notional,
        currency="EUR",
        issue_date=issue,
        maturity=maturity,
        tenor=ql.Period(ql.Semiannual),
        calendar=calendar,
        day_counter=dc,
        gearing=1.0,
        spread=0.0,
    )
    return InterestRateSwap(paying_leg=fixed_leg, receiving_leg=float_leg)


def test_irs_smoke() -> None:
    as_of, dc, disc_nodes, fwd_nodes = _build_curves()
    index = make_forecast_index("euribor6m", fwd_nodes)
    swap = _build_swap(as_of, dc)

    mtm = swap.mark_to_market(discount_nodes=disc_nodes, forecast_index=index)
    assert isinstance(mtm, float)

    pv01 = swap.ir01_discount(discount_nodes=disc_nodes, forecast_index=index)
    assert abs(pv01) > 0

    assert (
        abs(
            swap.pv01(discount_nodes=disc_nodes, forecast_index=index)
            - swap.dv01(discount_nodes=disc_nodes, forecast_index=index)
        )
        < 1_000_000
    )

    bumped = disc_nodes.bump(1.0)
    mtm_bumped = swap.mark_to_market(discount_nodes=bumped, forecast_index=index)
    fd = mtm_bumped - mtm
    assert abs(fd - pv01) < 1e-2 * 1_000_000
