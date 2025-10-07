from __future__ import annotations

from dataclasses import dataclass
from typing import List, Any

from QuantLib import Actual360, Actual365Fixed, ZeroCurve, BlackConstantVol, NullCalendar, SimpleQuote, Period

from .context import MarketContext


@dataclass
class ScenarioInstruction:
    target: str  # e.g. 'discount', 'vols', 'equity_spot', 'fx_spot', 'fx_fwd_points'
    key: Any  # e.g. currency, underlying, tuple, etc.
    shift: float
    relative: bool = False


@dataclass
class Scenario:
    name: str
    instructions: List[ScenarioInstruction]

    def apply(self, base_ctx: MarketContext, target_ctx: MarketContext) -> None:
        """
        Relink handles in target_ctx to stressed objects derived from base_ctx, as per instructions.
        base_ctx: reference market state (never mutated)
        target_ctx: context to be stressed (handles relinked)
        """
        # Start from the base context for every handle so that scenarios only
        # impact the parts they explicitly target. This avoids leaks from
        # previous scenario runs where a handle might have been stressed but is
        # not touched in the current scenario.
        for key, handle in base_ctx.discount.items():
            target_ctx.discount[key].linkTo(handle.currentLink())
        for key, handle in base_ctx.dividend.items():
            target_ctx.dividend[key].linkTo(handle.currentLink())
        for key, handle in base_ctx.vols.items():
            target_ctx.vols[key].linkTo(handle.currentLink())
        for key, handle in base_ctx.equity_spot.items():
            target_ctx.equity_spot[key].linkTo(handle.currentLink())
        for key, handle in base_ctx.fx_spot.items():
            target_ctx.fx_spot[key].linkTo(handle.currentLink())
        for pair, tenors in base_ctx.fx_fwd_points.items():
            for tenor, handle in tenors.items():
                target_ctx.fx_fwd_points[pair][tenor].linkTo(handle.currentLink())

        for instr in self.instructions:
            if instr.target == "discount":
                base_curve = base_ctx.discount[instr.key].currentLink()
                dc = Actual360()
                # Use pillar dates from context (as in build_dummy)
                tenors = ["1M", "3M", "6M", "9M", "1Y", "2Y"]
                dates = [base_ctx.as_of + Period(t) for t in tenors]
                rates = [base_curve.zeroRate(d, dc, 0, 1).rate() for d in dates]
                if instr.relative:
                    rates = [r * (1.0 + instr.shift) for r in rates]
                else:
                    rates = [r + instr.shift for r in rates]
                bumped = ZeroCurve(dates, rates, dc)
                target_ctx.discount[instr.key].linkTo(bumped)
            elif instr.target == "vols":
                base_vol = base_ctx.vols[instr.key].currentLink()
                level = base_vol.blackVol(base_ctx.as_of, 0.0)
                if instr.relative:
                    level *= 1.0 + instr.shift
                else:
                    level += instr.shift
                bumped = BlackConstantVol(base_ctx.as_of, NullCalendar(), level, Actual365Fixed())
                target_ctx.vols[instr.key].linkTo(bumped)
            elif instr.target == "equity_spot":
                base_quote = base_ctx.equity_spot[instr.key].currentLink()
                value = base_quote.value()
                if instr.relative:
                    value *= 1.0 + instr.shift
                else:
                    value += instr.shift
                new_quote = SimpleQuote(value)
                target_ctx.equity_spot[instr.key].linkTo(new_quote)
            elif instr.target == "fx_spot":
                base_quote = base_ctx.fx_spot[instr.key].currentLink()
                value = base_quote.value()
                if instr.relative:
                    value *= 1.0 + instr.shift
                else:
                    value += instr.shift
                new_quote = SimpleQuote(value)
                target_ctx.fx_spot[instr.key].linkTo(new_quote)
            elif instr.target == "fx_fwd_points":
                for tenor, handle in base_ctx.fx_fwd_points[instr.key].items():
                    base_quote = handle.currentLink()
                    value = base_quote.value()
                    if instr.relative:
                        value *= 1.0 + instr.shift
                    else:
                        value += instr.shift
                    new_quote = SimpleQuote(value)
                    target_ctx.fx_fwd_points[instr.key][tenor].linkTo(new_quote)


# Example scenario factory


def make_scenarios() -> List[Scenario]:
    return [
        Scenario(
            name="Rates up, Equities down",
            instructions=[
                ScenarioInstruction(target="discount", key="SEK", shift=0.0025, relative=False),
                ScenarioInstruction(target="equity_spot", key="OMX", shift=-0.05, relative=True),
            ],
        ),
        Scenario(
            name="Vols up, FX spot up",
            instructions=[
                ScenarioInstruction(target="vols", key="OMX_ATM", shift=0.02, relative=False),
                ScenarioInstruction(target="fx_spot", key=("SEK", "USD"), shift=0.03, relative=True),
            ],
        ),
    ]
