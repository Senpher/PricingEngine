import math

import QuantLib as ql

from pricingengine.termstructures.curve_nodes import CurveNodes


def test_flat_curve_discount_and_bump() -> None:
    as_of = ql.Date(1, 1, 2020)
    ql.Settings.instance().evaluationDate = as_of
    dc = ql.Actual365Fixed()
    nodes = CurveNodes(
        as_of=as_of,
        dates=[as_of + ql.Period(1, ql.Years)],
        quotes=[0.02],
        day_counter=dc,
        quote_kind="flat",
    )
    d = nodes.yts_handle().discount(as_of + ql.Period(5, ql.Years))
    t = dc.yearFraction(as_of, as_of + ql.Period(5, ql.Years))
    assert abs(d - math.exp(-0.02 * t)) < 1e-9

    bumped = nodes.bump(1.0)
    d_b = bumped.yts_handle().discount(as_of + ql.Period(5, ql.Years))
    assert abs(d_b - math.exp(-(0.02 + 0.0001) * t)) < 1e-9


def test_discount_curve_bump_recomputes() -> None:
    as_of = ql.Date(1, 1, 2020)
    ql.Settings.instance().evaluationDate = as_of
    dc = ql.Actual365Fixed()

    date1 = as_of + ql.Period(1, ql.Years)
    date5 = as_of + ql.Period(5, ql.Years)
    t1 = dc.yearFraction(as_of, date1)
    t5 = dc.yearFraction(as_of, date5)
    df1 = math.exp(-0.02 * t1)
    df5 = math.exp(-0.02 * t5)
    nodes = CurveNodes(
        as_of=as_of,
        dates=[date1, date5],
        quotes=[df1, df5],
        day_counter=dc,
        quote_kind="discount",
    )
    assert abs(nodes.discount_factor(date5) - df5) < 1e-12

    bumped = nodes.bump(1.0)
    d_b = bumped.discount_factor(date5)
    expected = df5 * math.exp(-0.0001 * t5)
    assert abs(d_b - expected) < 1e-12
