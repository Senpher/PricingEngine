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
from pricingengine.structures.curve_nodes import CurveNodes


def main() -> None:
    asof = Date.todaysDate()
    Settings.instance().evaluationDate = asof

    calendar = TARGET()
    issue = asof
    maturity = calendar.advance(issue, Period(5, Years))

    fixed_schedule = Schedule(
        issue,
        maturity,
        Period(12, Months),
        calendar,
        ModifiedFollowing,
        ModifiedFollowing,
        DateGeneration.Forward,
        False,
    )
    float_schedule = Schedule(
        issue,
        maturity,
        Period(6, Months),
        calendar,
        ModifiedFollowing,
        ModifiedFollowing,
        DateGeneration.Forward,
        False,
    )

    dc = Actual365Fixed()

    discount_nodes = CurveNodes(
        asof=asof,
        dates=[maturity],
        quotes=[0.02],
        day_count=dc,
        quote_kind="flat",
        role="discounting",
    )
    forecast_nodes = CurveNodes(
        asof=asof,
        dates=[maturity],
        quotes=[0.025],
        day_count=dc,
        quote_kind="flat",
        role="forecasting",
    )

    index = make_forecast_index("euribor6m", forecast_nodes)

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

    swap = InterestRateSwap(paying_leg=fixed_leg, receiving_leg=float_leg)

    mtm = swap.mtm(index, discount_nodes)
    pv01 = swap.pv01(index, discount_nodes)
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
