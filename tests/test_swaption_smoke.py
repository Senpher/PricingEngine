import QuantLib as ql

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg
from pricingengine.indices.index_utils import make_forecast_index
from pricingengine.irs import InterestRateSwap
from pricingengine.instruments import Swaption
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


def _build_swap(as_of, dc, index, discount_curve, *, issue=None):
    calendar = ql.TARGET()
    if issue is None:
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
        index=index,
        gearing=1.0,
        spread=0.0,
    )
    return InterestRateSwap(
        paying_leg=fixed_leg, receiving_leg=float_leg, discount_curve=discount_curve
    )


def test_swaption_smoke():
    as_of, dc, disc_nodes, fwd_nodes = _build_curves()
    index = make_forecast_index("euribor6m", fwd_nodes)
    expiry = as_of + ql.Period(1, ql.Years)
    swap = _build_swap(as_of, dc, index, disc_nodes.yts_handle, issue=expiry)
    swpt = Swaption(swap=swap, expiries=[expiry])

    mtm = swpt.mark_to_market()
    assert isinstance(mtm, float)

    vega = swpt.vega()
    assert isinstance(vega, float)

    atm = swpt.atm_strike()
    assert isinstance(atm, float)

    iv = swpt.implied_volatility(target_npv=mtm)
    assert iv > 0
