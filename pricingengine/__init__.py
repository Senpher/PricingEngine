"""PricingEngine public API."""

from QuantLib import Currency

from .instruments import (
    EuropeanVanillaOption,
    AmericanVanillaOption,
    BermudanVanillaOption,
    EuropeanDigitalOption,
    FXEuropeanVanillaOption,
    FXAmericanVanillaOption,
    FXBermudanVanillaOption,
    FXEuropeanDigitalOption,
    FxForward,
    Instrument,
    InterestRateSwap,
    Swaption,
)
from .instruments.common import FixedLeg, FloatingLeg, SwapLeg
from .termstructures import CurveNodes

CURRENCIES = {c().code(): c() for c in Currency.__subclasses__()}

__all__ = [
    "CURRENCIES",
    "CurveNodes",
    "Instrument",
    "InterestRateSwap",
    "FxForward",
    "EuropeanVanillaOption",
    "AmericanVanillaOption",
    "BermudanVanillaOption",
    "EuropeanDigitalOption",
    "FXEuropeanVanillaOption",
    "FXAmericanVanillaOption",
    "FXBermudanVanillaOption",
    "FXEuropeanDigitalOption",
    "Swaption",
]
