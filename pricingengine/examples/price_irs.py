"""Small demo wiring up flat curves and pricing an IRS."""

from __future__ import annotations

import pandas as pd
from QuantLib import (
    TARGET,
    Actual365Fixed,
    Date,
    DateGeneration,
    ModifiedFollowing,
    Months,
    Period,
    Schedule,
    Settings,
    Years,
)

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg
from pricingengine.indices.index_utils import make_forecast_index
from pricingengine.irs import InterestRateSwap
from pricingengine.termstructures.curve_nodes import CurveNodes


def main() -> None:
    as_of = Date.todaysDate()
    Settings.instance().evaluationDate = as_of

    calendar = TARGET()
    issue = as_of
    maturity = calendar.advance(issue, Period(5, Years))

    dc = Actual365Fixed()

    discount_nodes = CurveNodes(
        as_of=as_of,
        dates=[maturity],
        quotes=[0.02],
        day_counter=dc,
        quote_kind="flat",
        role="discounting",
    )
    forecast_nodes = CurveNodes(
        as_of=as_of,
        dates=[maturity],
        quotes=[0.025],
        day_counter=dc,
        quote_kind="flat",
        role="forecasting",
    )

    index = make_forecast_index("euribor6m", forecast_nodes)

    notional = 1_000_000
    fixed_leg = FixedLeg(
        valuation_date=as_of,
        nominal=notional,
        currency="EUR",
        issue_date=issue,
        maturity=maturity,
        tenor=Period(12, Months),
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
        tenor=Period(6, Months),
        calendar=calendar,
        day_counter=dc,
        gearing=1.0,
        spread=0.0,
    )

    swap = InterestRateSwap(paying_leg=fixed_leg, receiving_leg=float_leg)

    mtm = swap.mark_to_market(discount_nodes=discount_nodes, forecast_index=index)
    pv01 = swap.ir01_discount(discount_nodes=discount_nodes, forecast_index=index)
    print(f"MTM: {mtm:.2f}")
    print(f"PV01: {pv01:.2f}")

    rows = []
    for cf in fixed_leg.cashflows():
        rows.append({"leg": "fixed", "date": cf.date(), "amount": cf.amount()})
    for cf in float_leg.cashflows(forecast_index=index):
        rows.append({"leg": "float", "date": cf.date(), "amount": cf.amount()})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    print(df.head())


if __name__ == "__main__":
    main()
