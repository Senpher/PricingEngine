from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from QuantLib import SimpleQuote

from .context import MarketContext


class ScenarioProtocol(Protocol):
    name: str

    def apply(self, ctx: MarketContext) -> None: ...

    def undo(self, ctx: MarketContext) -> None: ...


@dataclass
class Scenario:
    name: str

    def apply(self, ctx: MarketContext) -> None:  # pragma: no cover - abstract method
        raise NotImplementedError

    def undo(self, ctx: MarketContext) -> None:  # pragma: no cover - abstract method
        raise NotImplementedError


QuoteAccessor = Callable[[MarketContext], SimpleQuote]


@dataclass
class QuoteShiftScenario(Scenario):
    accessor: QuoteAccessor
    shift: float
    relative: bool = False
    _previous: float | None = field(init=False, default=None, repr=False)

    def apply(self, ctx: MarketContext) -> None:
        quote = self.accessor(ctx)
        self._previous = quote.value()
        if self.relative:
            quote.setValue(self._previous * (1.0 + self.shift))
        else:
            quote.setValue(self._previous + self.shift)

    def undo(self, ctx: MarketContext) -> None:
        if self._previous is None:
            return
        quote = self.accessor(ctx)
        quote.setValue(self._previous)
        self._previous = None


@dataclass
class CurveParallelShiftScenario(Scenario):
    currency: str
    shift: float
    relative: bool = False
    _previous: float | None = field(init=False, default=None, repr=False)

    def apply(self, ctx: MarketContext) -> None:
        quote = ctx.discount_quotes[self.currency]
        self._previous = quote.value()
        if self.relative:
            quote.setValue(self._previous * (1.0 + self.shift))
        else:
            quote.setValue(self._previous + self.shift)

    def undo(self, ctx: MarketContext) -> None:
        if self._previous is None:
            return
        ctx.discount_quotes[self.currency].setValue(self._previous)
        self._previous = None


@dataclass
class VolShiftScenario(Scenario):
    code: str
    shift: float
    relative: bool = False
    _previous: float | None = field(init=False, default=None, repr=False)

    def apply(self, ctx: MarketContext) -> None:
        quote = ctx.vol_quotes[self.code]
        self._previous = quote.value()
        if self.relative:
            quote.setValue(self._previous * (1.0 + self.shift))
        else:
            quote.setValue(self._previous + self.shift)

    def undo(self, ctx: MarketContext) -> None:
        if self._previous is None:
            return
        ctx.vol_quotes[self.code].setValue(self._previous)
        self._previous = None


@dataclass
class CompositeScenario(Scenario):
    components: list[Scenario]

    def __init__(self, name: str, components: Iterable[Scenario]) -> None:
        super().__init__(name=name)
        self.components = list(components)

    def apply(self, ctx: MarketContext) -> None:
        for component in self.components:
            component.apply(ctx)

    def undo(self, ctx: MarketContext) -> None:
        for component in reversed(self.components):
            component.undo(ctx)


@dataclass
class ScenarioSet:
    """Iterable container over scenarios."""

    scenarios: list[Scenario]

    def __init__(self, scenarios: Iterable[Scenario]):
        self.scenarios = list(scenarios)

    def __iter__(self) -> Iterator[Scenario]:
        return iter(self.scenarios)

    def add(self, scenario: Scenario) -> None:
        self.scenarios.append(scenario)
