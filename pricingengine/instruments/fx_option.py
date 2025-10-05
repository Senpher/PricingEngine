from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional

from QuantLib import (
    Date,
    QuoteHandle,
    YieldTermStructureHandle,
    BlackVolTermStructureHandle,
)

from pricingengine.instruments.equity_option import (
    OptionEngineParameters,
    EuropeanVanillaOption,
    AmericanVanillaOption,
    BermudanVanillaOption,
    EuropeanDigitalOption,
)


# -------------------------
# FX = Garman–Kohlhagen by mapping:
#   foreign_curve  -> dividend_curve (q)
#   domestic_curve -> risk_free_curve (r)
# -------------------------


@dataclass(frozen=True, kw_only=True, init=False)
class FXEuropeanVanillaOption(EuropeanVanillaOption):
    def __init__(
        self,
        *,
        quantity: int,
        contract_size: int,
        option_type: int,  # QLOption.Call or QLOption.Put
        strike: float,
        maturity: Date,
        spot: QuoteHandle,
        foreign_curve: YieldTermStructureHandle,  # q
        domestic_curve: YieldTermStructureHandle,  # r
        vol: BlackVolTermStructureHandle,
        engine_params: Optional[OptionEngineParameters] = None,
        greek_bump_policy: str = "sticky_strike",
    ) -> None:
        super().__init__(
            quantity=quantity,
            contract_size=contract_size,
            option_type=option_type,
            strike=strike,
            maturity=maturity,
            spot=spot,
            dividend_curve=foreign_curve,  # map q
            risk_free_curve=domestic_curve,  # map r
            vol=vol,
            engine_params=engine_params or OptionEngineParameters.analytic(),
            greek_bump_policy=greek_bump_policy,
        )


@dataclass(frozen=True, kw_only=True, init=False)
class FXEuropeanDigitalOption(EuropeanDigitalOption):
    def __init__(
        self,
        *,
        quantity: int,
        contract_size: int,
        option_type: int,
        cash_payoff: float,
        strike: float,
        maturity: Date,
        spot: QuoteHandle,
        foreign_curve: YieldTermStructureHandle,
        domestic_curve: YieldTermStructureHandle,
        vol: BlackVolTermStructureHandle,
        engine_params: Optional[OptionEngineParameters] = None,
        greek_bump_policy: str = "sticky_strike",
    ) -> None:
        super().__init__(
            quantity=quantity,
            contract_size=contract_size,
            option_type=option_type,
            cash_payoff=cash_payoff,
            strike=strike,
            maturity=maturity,
            spot=spot,
            dividend_curve=foreign_curve,
            risk_free_curve=domestic_curve,
            vol=vol,
            engine_params=engine_params or OptionEngineParameters.analytic(),
            greek_bump_policy=greek_bump_policy,
        )


@dataclass(frozen=True, kw_only=True, init=False)
class FXAmericanVanillaOption(AmericanVanillaOption):
    def __init__(
        self,
        *,
        quantity: int,
        contract_size: int,
        option_type: int,
        strike: float,
        maturity: Date,
        spot: QuoteHandle,
        foreign_curve: YieldTermStructureHandle,
        domestic_curve: YieldTermStructureHandle,
        vol: BlackVolTermStructureHandle,
        engine_params: Optional[OptionEngineParameters] = None,
        greek_bump_policy: str = "sticky_strike",
    ) -> None:
        super().__init__(
            quantity=quantity,
            contract_size=contract_size,
            option_type=option_type,
            strike=strike,
            maturity=maturity,
            spot=spot,
            dividend_curve=foreign_curve,
            risk_free_curve=domestic_curve,
            vol=vol,
            # trees/FD are typical defaults for American; feel free to change
            engine_params=engine_params or OptionEngineParameters.fd(nt=200, nx=400),
            greek_bump_policy=greek_bump_policy,
        )


@dataclass(frozen=True, kw_only=True, init=False)
class FXBermudanVanillaOption(BermudanVanillaOption):
    def __init__(
        self,
        *,
        quantity: int,
        contract_size: int,
        option_type: int,
        strike: float,
        exercise_dates: Tuple[Date, ...],
        spot: QuoteHandle,
        foreign_curve: YieldTermStructureHandle,
        domestic_curve: YieldTermStructureHandle,
        vol: BlackVolTermStructureHandle,
        engine_params: Optional[OptionEngineParameters] = None,
        greek_bump_policy: str = "sticky_strike",
    ) -> None:
        super().__init__(
            quantity=quantity,
            contract_size=contract_size,
            option_type=option_type,
            strike=strike,
            exercise_dates=exercise_dates,
            spot=spot,
            dividend_curve=foreign_curve,
            risk_free_curve=domestic_curve,
            vol=vol,
            engine_params=engine_params or OptionEngineParameters.fd(nt=200, nx=400),
            greek_bump_policy=greek_bump_policy,
        )
