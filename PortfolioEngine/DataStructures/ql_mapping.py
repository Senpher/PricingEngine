from contextlib import contextmanager
from enum import Enum

from QuantLib import (
    TARGET,
    Actual360,
    ActualActual,
    EURCurrency,
    GBPCurrency,
    IborIndex,
    ModifiedFollowing,
    NOKCurrency,
    Period,
    SEKCurrency,
    Settings,
    Thirty360,
    USDCurrency,
    YieldTermStructureHandle,
)
from QuantLib import Date as QLDate

from PricingEngine.Instruments.Common import (
    AmortizedFixedLeg,
    AmortizedFloatingLeg,
    FixedLeg,
    FloatingLeg,
)


class QlDayCountMapper(Enum):
    Actual360 = Actual360()
    Thirty360 = Thirty360(Thirty360.ISDA)
    ActualActual = ActualActual(ActualActual.ISDA)


class QlSwapLegMapper(Enum):
    amortized_fixed = AmortizedFixedLeg
    amortized_floating = AmortizedFloatingLeg
    fixed = FixedLeg
    floating = FloatingLeg


class QlCcyMapper(Enum):
    USD = USDCurrency()
    EUR = EURCurrency()
    GBP = GBPCurrency()
    SEK = SEKCurrency()
    NOK = NOKCurrency()


class GenericIbor(IborIndex):
    def __init__(self, tenor: str, currency: str, h: YieldTermStructureHandle):
        super().__init__(
            "GENERIC-IBOR",
            Period(tenor),
            2,
            QlCcyMapper[currency.upper()].value,
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
