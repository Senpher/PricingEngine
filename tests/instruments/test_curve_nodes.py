from __future__ import annotations

from dataclasses import FrozenInstanceError
from math import exp, log

import pytest
from QuantLib import (
    Actual365Fixed,
    Continuous,
    Date,
    DayCounter,
    SavedSettings,
    Settings,
    Simple,
)

from pricingengine.termstructures.curve_nodes import CurveNodes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def as_of() -> Date:
    return Date(1, 1, 2024)


@pytest.fixture
def day_counter() -> DayCounter:
    return Actual365Fixed()


@pytest.fixture(autouse=True)
def _ql_saved_settings(as_of: Date):
    with SavedSettings():
        Settings.instance().evaluationDate = as_of
        yield


@pytest.fixture
def yearly_dates(as_of: Date) -> tuple[Date, Date, Date]:
    return (
        Date(1, 1, 2025),
        Date(1, 1, 2026),
        Date(1, 1, 2027),
    )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_curve_nodes_requires_at_least_one_node(as_of: Date, day_counter: DayCounter) -> None:
    with pytest.raises(ValueError, match="at least one node"):
        CurveNodes(
            as_of=as_of,
            dates=(),
            quotes=(),
            day_counter=day_counter,
        )


def test_curve_nodes_requires_matching_date_and_quote_lengths(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    with pytest.raises(ValueError, match="same length"):
        CurveNodes(
            as_of=as_of,
            dates=yearly_dates,
            quotes=(0.01, 0.02),
            day_counter=day_counter,
        )


def test_curve_nodes_requires_strictly_increasing_dates(as_of: Date, day_counter: DayCounter) -> None:
    repeated_date = Date(1, 1, 2025)
    with pytest.raises(ValueError, match="strictly increasing"):
        CurveNodes(
            as_of=as_of,
            dates=(repeated_date, repeated_date),
            quotes=(0.01, 0.02),
            day_counter=day_counter,
        )


def test_discount_curve_quotes_must_lie_between_zero_and_one(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    with pytest.raises(ValueError, match="discount factors must lie"):
        CurveNodes(
            as_of=as_of,
            dates=yearly_dates[:2],
            quotes=(1.01, 0.95),
            day_counter=day_counter,
            quote_kind="discount",
        )


# ---------------------------------------------------------------------------
# Yield term structure handles
# ---------------------------------------------------------------------------


def test_yts_handle_flat_zero_curve_single_node(as_of: Date, day_counter: DayCounter) -> None:
    maturity = Date(1, 1, 2026)
    zero_rate = 0.015
    curve = CurveNodes(
        as_of=as_of,
        dates=(maturity,),
        quotes=(zero_rate,),
        day_counter=day_counter,
        quote_kind="zero",
    )

    time = day_counter.yearFraction(as_of, maturity)
    expected_discount = exp(-zero_rate * time)

    assert curve.discount_factor(maturity) == pytest.approx(expected_discount)
    assert curve.to_handle() is curve.yts_handle
    assert curve.yts_handle is curve.yts_handle  # cached_property guarantees reuse


def test_yts_handle_zero_curve_multiple_nodes(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    zeros = (0.01, 0.0125, 0.015)
    curve = CurveNodes(
        as_of=as_of,
        dates=yearly_dates,
        quotes=zeros,
        day_counter=day_counter,
        quote_kind="zero",
    )

    for date, zero in zip(yearly_dates, zeros):
        observed_zero = curve.yts_handle.zeroRate(date, day_counter, Continuous).rate()
        assert observed_zero == pytest.approx(zero, abs=5e-7)

    assert curve.nodes == tuple(zip(yearly_dates, zeros))


def test_yts_handle_discount_curve_inserts_as_of_discount(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    discounts = (0.99, 0.975, 0.94)
    curve = CurveNodes(
        as_of=as_of,
        dates=yearly_dates,
        quotes=discounts,
        day_counter=day_counter,
        quote_kind="discount",
    )

    assert curve.discount_factor(as_of) == pytest.approx(1.0)
    for date, discount in zip(yearly_dates, discounts):
        assert curve.discount_factor(date) == pytest.approx(discount)


def test_discount_curve_requires_at_least_two_nodes(as_of: Date, day_counter: DayCounter) -> None:
    curve = CurveNodes(
        as_of=as_of,
        dates=(Date(1, 1, 2025),),
        quotes=(0.99,),
        day_counter=day_counter,
        quote_kind="discount",
    )

    with pytest.raises(ValueError, match="at least two discount nodes"):
        _ = curve.yts_handle


def test_forward_curve_requires_at_least_two_nodes(as_of: Date, day_counter: DayCounter) -> None:
    curve = CurveNodes(
        as_of=as_of,
        dates=(Date(1, 1, 2025),),
        quotes=(0.02,),
        day_counter=day_counter,
        quote_kind="forward",
    )

    with pytest.raises(ValueError, match="forward curve needs at least two nodes"):
        _ = curve.yts_handle


def test_forward_curve_discount_factors_from_constant_forwards(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    forward_rate = 0.021
    forwards = (forward_rate,) * len(yearly_dates)
    curve = CurveNodes(
        as_of=as_of,
        dates=yearly_dates,
        quotes=forwards,
        day_counter=day_counter,
        quote_kind="forward",
    )

    for start, end in zip(yearly_dates[:-1], yearly_dates[1:]):
        observed_interval_forward = curve.yts_handle.forwardRate(start, end, day_counter, Simple).rate()
        assert observed_interval_forward == pytest.approx(forward_rate, abs=5e-4)


def test_flat_curve_requires_exactly_one_quote(as_of: Date, day_counter: DayCounter) -> None:
    maturity = Date(1, 1, 2026)

    with pytest.raises(ValueError, match="expects exactly one zero rate"):
        CurveNodes(
            as_of=as_of,
            dates=(maturity, Date(1, 1, 2027)),
            quotes=(0.02, 0.025),
            day_counter=day_counter,
            quote_kind="flat",
        ).yts_handle


def test_unknown_quote_kind_raises(attempted_kind: str = "mystery") -> None:
    as_of = Date(1, 1, 2024)
    day_counter = Actual365Fixed()
    curve = CurveNodes(
        as_of=as_of,
        dates=(Date(1, 1, 2025),),
        quotes=(0.01,),
        day_counter=day_counter,
        quote_kind=attempted_kind,
    )

    with pytest.raises(ValueError, match="Unsupported quote_kind"):
        _ = curve.yts_handle


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------


def test_discount_factor_matches_handle_discount(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    zeros = (0.01, 0.0125, 0.015)
    curve = CurveNodes.from_zeros(
        as_of=as_of,
        dates=yearly_dates,
        zeros=zeros,
        day_counter=day_counter,
    )

    target_date = yearly_dates[1]
    assert curve.discount_factor(target_date) == pytest.approx(curve.yts_handle.discount(target_date))


def test_curve_nodes_are_immutable(as_of: Date, day_counter: DayCounter) -> None:
    curve = CurveNodes.from_flat(
        as_of=as_of,
        maturity=Date(1, 1, 2026),
        zero=0.01,
        day_counter=day_counter,
    )

    with pytest.raises(FrozenInstanceError):
        curve.quotes = (0.02,)


def test_convenience_constructors_configure_expected_metadata(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    zero_curve = CurveNodes.from_zeros(
        as_of=as_of,
        dates=yearly_dates,
        zeros=(0.01, 0.015, 0.02),
        day_counter=day_counter,
        role="discounting",
    )
    assert zero_curve.quote_kind == "zero"
    assert zero_curve.role == "discounting"

    discount_curve = CurveNodes.from_discounts(
        as_of=as_of,
        dates=yearly_dates[:2],
        discounts=(0.99, 0.97),
        day_counter=day_counter,
        role="other",
    )
    assert discount_curve.quote_kind == "discount"
    assert discount_curve.role == "other"

    forward_curve = CurveNodes.from_forwards(
        as_of=as_of,
        dates=yearly_dates,
        forwards=(0.02, 0.022, 0.023),
        day_counter=day_counter,
    )
    assert forward_curve.quote_kind == "forward"
    assert forward_curve.role == "forecasting"

    maturity = Date(1, 1, 2028)
    flat_curve = CurveNodes.from_flat(
        as_of=as_of,
        maturity=maturity,
        zero=0.0175,
        day_counter=day_counter,
    )
    assert flat_curve.quote_kind == "flat"
    assert tuple(flat_curve.dates) == (maturity,)


# ---------------------------------------------------------------------------
# Bump mechanics
# ---------------------------------------------------------------------------


def test_bump_zero_curve_adds_parallel_shift(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    zeros = (0.01, 0.015, 0.02)
    curve = CurveNodes.from_zeros(
        as_of=as_of,
        dates=yearly_dates,
        zeros=zeros,
        day_counter=day_counter,
    )

    bumped = curve.bump(25)

    assert bumped is not curve
    assert bumped.quote_kind == curve.quote_kind
    assert bumped.role == curve.role
    expected = tuple(z + 0.0025 for z in zeros)
    assert bumped.quotes == expected
    assert curve.quotes == zeros  # original untouched


def test_bump_flat_curve_behaves_like_zero_curve(as_of: Date, day_counter: DayCounter) -> None:
    curve = CurveNodes.from_flat(
        as_of=as_of,
        maturity=Date(1, 1, 2027),
        zero=0.013,
        day_counter=day_counter,
    )

    bumped = curve.bump(-15)
    assert bumped.quotes == (curve.quotes[0] - 0.0015,)


def test_bump_discount_curve_converts_to_rates_and_back(as_of: Date, day_counter: DayCounter) -> None:
    dates = (as_of, Date(1, 7, 2024), Date(1, 1, 2025))
    discounts = (1.0, 0.985, 0.962)
    curve = CurveNodes(
        as_of=as_of,
        dates=dates,
        quotes=discounts,
        day_counter=day_counter,
        quote_kind="discount",
    )

    bumped = curve.bump(10)

    assert bumped.quote_kind == "discount"
    assert bumped.role == curve.role
    assert bumped.dates == dates

    for date, original_df, bumped_df in zip(dates, discounts, bumped.quotes):
        time = day_counter.yearFraction(as_of, date)
        if time <= 0.0:
            assert bumped_df == pytest.approx(original_df)
            continue
        rate = -log(original_df) / time
        expected_df = exp(-(rate + 0.001) * time)
        assert bumped_df == pytest.approx(expected_df)


def test_bump_forward_curve_shifts_forwards(
    as_of: Date, day_counter: DayCounter, yearly_dates: tuple[Date, Date, Date]
) -> None:
    forwards = (0.02, 0.021, 0.022)
    curve = CurveNodes.from_forwards(
        as_of=as_of,
        dates=yearly_dates,
        forwards=forwards,
        day_counter=day_counter,
    )

    bumped = curve.bump(-5)
    expected = tuple(f - 0.0005 for f in forwards)
    assert bumped.quotes == expected
    assert curve.quotes == forwards
