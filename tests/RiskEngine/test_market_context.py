from __future__ import annotations

import pytest
from QuantLib import Date, Settings

from RiskEngine.context import MarketContext


def test_build_dummy_context_sets_expected_handles() -> None:
    ctx = MarketContext.build_dummy()

    assert set(ctx.discount_handles) == {"SEK", "USD"}
    assert set(ctx.dividend_handles) == {"OMX"}
    assert set(ctx.vol_handles) == {"OMX_ATM"}
    assert set(ctx.equity_spot_handles) == {"OMX"}
    assert {"SEK", "USD"} <= {curr for pair in ctx.fx_spot_handles for curr in pair}


def test_at_eval_sets_quantlib_settings() -> None:
    ctx = MarketContext.build_dummy()
    Settings.instance().evaluationDate = Date(1, 1, 2000)

    with ctx.at_eval():
        assert Settings.instance().evaluationDate == ctx.evaluation_date

    assert Settings.instance().evaluationDate == Date(1, 1, 2000)


def test_discount_handle_updates_with_quote_changes() -> None:
    ctx = MarketContext.build_dummy()
    with ctx.at_eval():
        base_df = ctx.discount["SEK"].discount(Date(2, 1, 2025))

    ctx.discount_quotes["SEK"].setValue(ctx.discount_quotes["SEK"].value() + 0.01)

    with ctx.at_eval():
        bumped_df = ctx.discount["SEK"].discount(Date(2, 1, 2025))

    assert bumped_df != pytest.approx(base_df)
