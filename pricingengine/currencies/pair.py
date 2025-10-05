from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from pricingengine.currencies import CURRENCIES


def split(xs: str, n: int, rs: tuple[str]) -> tuple[str]:
    """Splits an input string into groups of `n` characters each."""
    if not xs:
        return rs
    else:
        return split(xs[n:], n, rs + (xs[:n],))


def split_ticker(ticker: str) -> Callable[[str], tuple[str]]:
    """Split `ticker` into groups of three characters."""
    return split(ticker, 3, ())


@dataclass(order=True, frozen=True)
class CurrencyPair:
    """
    Class for representing a currency pair.

    A currency pair consists of two currencies: the base currency and the price
    currency. It is denoted with a ticker symbol C1C2 where C1 and C2 are,
    respective, the base and the price currency and represents the amount of C2
    bought for selling a unit of C1.
    """

    base_currency: str
    price_currency: str

    def __post_init__(self):
        if self.base_currency not in CURRENCIES:
            raise ValueError("'base_currency' is not supported in QuantLib")
        if self.price_currency not in CURRENCIES:
            raise ValueError("'price_currency' is not supported in QuantLib")

    @property
    def dimension(self):
        return ExchangeRateDimension.from_tickers(
            numerator=self.price_currency, denominator=self.base_currency
        )

    @property
    def ticker_symbol(self) -> str:
        return f"{self.base_currency}{self.price_currency}"

    def __contains__(self, x: str) -> bool:
        return x == self.base_currency or x == self.price_currency

    def __invert__(self) -> CurrencyPair:
        """Inverts a currency pair (e.g., USDSEK becomes SEKUSD)."""
        return CurrencyPair(
            base_currency=self.price_currency, price_currency=self.base_currency
        )

    def __mul__(self, other: CurrencyPair) -> CurrencyPair:
        """
        Multiplies two currency pairs and constructs a new currency pair.

        With currency pairs C1C2 and C3C4 it is possible to construct a new
        currency pair C1C3 by multiplying C1C2 and C3C4 when C2 is the same as
        C3. This is called an intermediate currency. For a currency to be an
        intermediate currency it must be the price currency in one currency
        pair and the base currency in the other.
        """
        d = (self.dimension * other.dimension).simplify()
        return CurrencyPair.from_exchange_rate_dimension(d)

    @classmethod
    def from_exchange_rate_dimension(cls, d: ExchangeRateDimension) -> CurrencyPair:
        """Creates a simple currency pair (e.g., USDSEK) from `ExchangeRateDimension`."""
        if d.numerator.total() == d.denominator.total() == 1:
            base_currency = next(iter(d.denominator.keys()))
            price_currency = next(iter(d.numerator.keys()))
            return CurrencyPair(
                base_currency=base_currency, price_currency=price_currency
            )
        else:
            raise RuntimeError(
                "cannot create a currency pair with more than two currencies"
            )


@dataclass(order=True, frozen=True)
class ExchangeRateDimension:
    """
    Class for providing a unit dimension to a currency pair's exchange rate.

    Currency pair C1C2 represents the amount of C2 bought for selling a unit of
    C1. Therefore, it's exchange rate has the dimension of C2/C1, where C2 is
    the numerator and C1 is the denominator of the exchange rate's dimension.

    This class can be used for representing even complex exchange rates, e.g.,
    C2/C1 * C4/C3, with more than two currencies. However, these complex
    exchange rates cannot be represented with only one base and price currency
    using `CurrencyPair`.

    Example:

    [USDSEK] * [SEKEUR] = SEK/USD * EUR/SEK = EUR/USD = [USDEUR]

    Square brackets denote unit dimensions of a currency pair.
    """

    numerator: Counter
    denominator: Counter

    def __post_init__(self) -> None:
        if self.numerator.total() != self.denominator.total():
            raise RuntimeError(
                "'numerator' and 'denominator' must have the same number of currencies"
            )

    def __contains__(self, x: str) -> bool:
        return x in self.numerator or x in self.denominator

    def __invert__(self) -> ExchangeRateDimension:
        """
        Mathematical inversion.

        Example:

        1/[EURUSD] = 1/(USD/EUR) = EUR/USD = [USDEUR]
        """
        return ExchangeRateDimension(
            numerator=self.denominator, denominator=self.numerator
        )

    def __mul__(self, other: ExchangeRateDimension) -> ExchangeRateDimension:
        """
        Mathematical multiplication.

        Multiplication of `ExchangeRateDimension` follows some of the principles of
        mathamatical multiplicaiton:

        Identity property:

        1 * [SEKUSD] = 1 * USD/SEK = USD/SEK,

        Commutative property:

        (USD/SEK) * (SEK/NOK) = (SEK/NOK) * (USD/SEK)

        Associative property:

        (USD/SEK) * ((SEK/NOK) * (NOK/EUR)) = ((USD/SEK) * (SEK/NOK)) * (NOK/EUR),

        This function is also endomorphism and adheres to the closure property
        of multiplication.
        """
        numerator = self.numerator + other.numerator
        denominator = self.denominator + other.denominator
        return ExchangeRateDimension(numerator=numerator, denominator=denominator)

    def __truediv__(self, other: ExchangeRateDimension) -> ExchangeRateDimension:
        """
        Mathematical division.

        Division and mulitplication are related though inversion

        (USD/SEK)/(NOK/SEK) = (USD/SEK) * 1/(NOK/SEK) = (USD/SEK) * (SEK/NOK).
        """
        return self * other.__invert__()

    def simplify(self) -> ExchangeRateDimension:
        common = self.numerator & self.denominator
        numerator, denominator = self.numerator - common, self.denominator - common
        return ExchangeRateDimension(numerator=numerator, denominator=denominator)

    @classmethod
    def from_tickers(cls, numerator: str, denominator: str) -> ExchangeRateDimension:
        return cls.from_tuples(
            numerator=split_ticker(numerator), denominator=split_ticker(denominator)
        )

    @classmethod
    def from_tuples(
        cls, numerator: tuple[str], denominator: tuple[str]
    ) -> ExchangeRateDimension:
        return cls(numerator=Counter(numerator), denominator=Counter(denominator))
