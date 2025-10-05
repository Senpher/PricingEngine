from enum import Enum
from contextlib import contextmanager
from QuantLib import Settings, Date as QLDate
from QuantLib import Actual360, ActualActual, Thirty360
from QuantLib import (
    IborIndex,
    TARGET,
    YieldTermStructureHandle,
    Period,
    ModifiedFollowing,
)
from QuantLib import NOKCurrency, USDCurrency, EURCurrency, GBPCurrency, SEKCurrency
from pricingengine.cashflows.swap_leg import (
    AmortizedFixedLeg,
    AmortizedFloatingLeg,
    FixedLeg,
    FloatingLeg,
)


class QL_day_count_mapper(Enum):
    Actual360 = Actual360()
    Thirty360 = Thirty360(Thirty360.ISDA)
    ActualActual = ActualActual(ActualActual.ISDA)


class QL_swap_leg_mapper(Enum):
    amortized_fixed = AmortizedFixedLeg
    amortized_floating = AmortizedFloatingLeg
    fixed = FixedLeg
    floating = FloatingLeg


class QL_ccy_mapper(Enum):
    USD = USDCurrency()
    EUR = EURCurrency()
    GBP = GBPCurrency()
    SEK = SEKCurrency()
    NOK = NOKCurrency()


class generic_ibor(IborIndex):
    def __init__(self, tenor: str, currency: str, h: YieldTermStructureHandle):
        super().__init__(
            "GENERIC-IBOR",
            Period(tenor),
            2,
            QL_ccy_mapper[currency.upper()].value,
            TARGET(),
            ModifiedFollowing,
            False,
            Actual360(),
            h,
        )


# Function to determine if you should take the inverse
def fx_base_price_invert(pair: str) -> bool:
    inverted_fx_currencies = {"EUR", "NZD", "AUD", "GBP"}
    return pair in inverted_fx_currencies


def fx_direction_alignment(ccy: str, rate: float) -> float:
    inverted_fx_currencies = {"EUR", "NZD", "AUD", "GBP"}
    if ccy in inverted_fx_currencies:
        return 1 / rate
    else:
        return rate


# Handling evaluation date


@contextmanager
def ql_eval_date(d: QLDate):
    prev = Settings.instance().evaluationDate
    Settings.instance().evaluationDate = d
    try:
        yield
    finally:
        Settings.instance().evaluationDate = prev
