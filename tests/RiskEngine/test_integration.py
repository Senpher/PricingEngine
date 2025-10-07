from __future__ import annotations

import pytest
from QuantLib import (
    TARGET,
    Actual365Fixed,
    ConstantSwaptionVolatility,
    IborIndex,
    ModifiedFollowing,
    Normal,
    Option,
    Period,
    SEKCurrency,
    ShiftedLognormal,
    SwaptionVolatilityStructureHandle,
)

from PricingEngine.Instruments.Common import FloatingLeg
from PricingEngine.Instruments.cross_currency_swap import CrossCurrencySwap
from PricingEngine.Instruments.equity_option import EuropeanVanillaOption
from PricingEngine.Instruments.fx_forward import FxForward
from PricingEngine.Instruments.fx_option import FXEuropeanVanillaOption
from PricingEngine.Instruments.interest_rate_swap import FixedLeg, InterestRateSwap
from PricingEngine.Instruments.swaption import Swaption
from RiskEngine.context import MarketContext
from RiskEngine.engine import RiskEngine
from RiskEngine.portfolio import Portfolio, Position
from RiskEngine.scenarios import Scenario, ScenarioInstruction


@pytest.fixture()
def context() -> MarketContext:
    return MarketContext.build_dummy()


@pytest.fixture()
def portfolio(context: MarketContext) -> Portfolio:
    as_of = context.as_of
    target = TARGET()
    dc365 = Actual365Fixed()

    def fx_points() -> list[dict[str, float]]:
        base_points = context.fx_fwd_points[("SEK", "USD")]

        def tenor_key(item: tuple[str, object]) -> tuple[int, int]:
            period = Period(item[0])
            return period.length(), period.units()

        return [
            {"tenor": tenor, "points": handle.value()} for tenor, handle in sorted(base_points.items(), key=tenor_key)
        ]

    stibor6m = IborIndex(
        "STIBOR6M",
        Period("6M"),
        2,
        SEKCurrency(),
        target,
        ModifiedFollowing,
        False,
        dc365,
        context.discount["SEK"],
    )
    stibor6m.addFixing(as_of - 2, 0.02)

    def swaption_vol(level: float, model: str) -> SwaptionVolatilityStructureHandle:
        vol_type = Normal if model.lower() == "bachelier" else ShiftedLognormal
        return SwaptionVolatilityStructureHandle(
            ConstantSwaptionVolatility(0, target, ModifiedFollowing, level, dc365, vol_type)
        )

    with context.at_eval():
        positions: list[Position] = []

        # Equity options (OMX and SPX)
        equity_specs = [
            ("EQ_OMX_CALL_JAN27", "OMX", Option.Call, 2400.0, Period("18M"), 5, 50),
            ("EQ_OMX_PUT_JUL27", "OMX", Option.Put, 2200.0, Period("24M"), -3, 25),
            ("EQ_SPX_CALL_MAR26", "SPX", Option.Call, 5500.0, Period("9M"), 4, 10),
            ("EQ_SPX_PUT_DEC26", "SPX", Option.Put, 5000.0, Period("17M"), 2, 15),
        ]
        for name, ticker, opt_type, strike, maturity_tenor, quantity, contract_size in equity_specs:
            positions.append(
                Position(
                    name,
                    EuropeanVanillaOption(
                        quantity=quantity,
                        contract_size=contract_size,
                        option_type=opt_type,
                        strike=strike,
                        maturity=as_of + maturity_tenor,
                        spot=context.equity_spot[ticker],
                        dividend_curve=context.dividend[ticker],
                        risk_free_curve=context.discount["SEK" if ticker == "OMX" else "USD"],
                        vol=context.vols["OMX_ATM" if ticker == "OMX" else "SPX_ATM"],
                    ),
                )
            )

        # FX options (USD/SEK)
        fx_option_specs = [
            ("FXOPT_CALL_3M", Option.Call, 9.7, Period("3M"), 1, 1_000_000),
            ("FXOPT_PUT_6M", Option.Put, 9.4, Period("6M"), -1, 750_000),
            ("FXOPT_CALL_9M", Option.Call, 10.1, Period("9M"), 2, 500_000),
            ("FXOPT_PUT_1Y", Option.Put, 9.2, Period("12M"), -2, 600_000),
        ]
        for name, opt_type, strike, tenor, quantity, contract_size in fx_option_specs:
            positions.append(
                Position(
                    name,
                    FXEuropeanVanillaOption(
                        quantity=quantity,
                        contract_size=contract_size,
                        option_type=opt_type,
                        strike=strike,
                        maturity=as_of + tenor,
                        spot=context.fx_spot[("SEK", "USD")],
                        foreign_curve=context.discount["USD"],
                        domestic_curve=context.discount["SEK"],
                        vol=context.vols["SPX_ATM"],
                    ),
                )
            )

        # FX forwards
        fx_forward_specs = [
            ("FXFWD_LONG_1M", True, Period("1M"), 9.55, 2_000_000),
            ("FXFWD_SHORT_3M", False, Period("3M"), 9.70, 1_500_000),
            ("FXFWD_LONG_6M", True, Period("6M"), 9.85, 1_800_000),
            ("FXFWD_SHORT_12M", False, Period("12M"), 10.05, 2_200_000),
        ]
        for name, long_base, tenor, forward_price, nominal in fx_forward_specs:
            positions.append(
                Position(
                    name,
                    FxForward(
                        nominal=nominal,
                        forward_price=forward_price,
                        maturity=as_of + tenor,
                        base_currency="USD",
                        price_currency="SEK",
                        long_base=long_base,
                        spot=context.fx_spot[("SEK", "USD")],
                        discount_domestic=context.discount["SEK"],
                        fx_fwd_pts_curve=fx_points(),
                    ),
                )
            )

        # Interest rate swaps (SEK)
        irs_specs = [
            ("IRS_SEK_9M_PAYER", Period("9M"), 0.0205, 0.0000, 5_000_000),
            ("IRS_SEK_12M_RECEIVER", Period("12M"), 0.0190, 0.0005, 4_500_000),
            ("IRS_SEK_18M_PAYER", Period("18M"), 0.0215, -0.0003, 6_000_000),
            ("IRS_SEK_24M_RECEIVER", Period("24M"), 0.0200, 0.0007, 5_500_000),
        ]
        for idx, (name, tenor, fixed_rate, spread, nominal) in enumerate(irs_specs):
            issue_date = as_of
            maturity = issue_date + tenor
            fixed_leg = FixedLeg(
                nominal=nominal,
                currency="SEK",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("6M"),
                calendar=target,
                day_counter=dc365,
                rate=fixed_rate,
            )
            float_leg = FloatingLeg(
                nominal=nominal,
                currency="SEK",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("6M"),
                calendar=target,
                day_counter=dc365,
                index=stibor6m,
                gearing=1.0,
                spread=spread,
            )
            if idx % 2 == 0:
                paying, receiving = fixed_leg, float_leg
            else:
                paying, receiving = float_leg, fixed_leg
            positions.append(
                Position(
                    name,
                    InterestRateSwap(
                        paying_leg=paying,
                        receiving_leg=receiving,
                        discount_curve=context.discount["SEK"],
                    ),
                )
            )

        # Swaptions (SEK)
        swaption_specs = [
            ("SWPT_SEK_3M_12M", Period("3M"), Period("12M"), 0.0205, 0.0000, 0.22, True, "bachelier"),
            ("SWPT_SEK_6M_12M", Period("6M"), Period("12M"), 0.0195, 0.0003, 0.18, False, "black"),
            ("SWPT_SEK_9M_9M", Period("9M"), Period("9M"), 0.0210, -0.0002, 0.25, True, "black"),
            ("SWPT_SEK_12M_12M", Period("12M"), Period("12M"), 0.0200, 0.0005, 0.19, False, "bachelier"),
        ]
        for name, expiry_tenor, swap_tenor, fixed_rate, spread, vol_level, is_long, vol_model in swaption_specs:
            issue_date = as_of + expiry_tenor
            maturity = issue_date + swap_tenor
            nominal = 7_500_000
            fixed_leg = FixedLeg(
                nominal=nominal,
                currency="SEK",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("6M"),
                calendar=target,
                day_counter=dc365,
                rate=fixed_rate,
            )
            float_leg = FloatingLeg(
                nominal=nominal,
                currency="SEK",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("6M"),
                calendar=target,
                day_counter=dc365,
                index=stibor6m,
                gearing=1.0,
                spread=spread,
            )
            swap = InterestRateSwap(
                paying_leg=fixed_leg,
                receiving_leg=float_leg,
                discount_curve=context.discount["SEK"],
            )
            positions.append(
                Position(
                    name,
                    Swaption(
                        irs=swap,
                        vol_surface=swaption_vol(vol_level, vol_model),
                        expiries=[issue_date],
                        settlement="physical",
                        vol_model=vol_model,
                        is_long=is_long,
                    ),
                )
            )

        # Cross currency swaps (SEK vs USD)
        ccs_specs = [
            ("CCS_SEKUSD_6M", Period("6M"), 0.0210, 0.0110, 10_000_000, 1_050_000),
            ("CCS_SEKUSD_9M", Period("9M"), 0.0200, 0.0120, 9_500_000, 1_100_000),
            ("CCS_SEKUSD_12M", Period("12M"), 0.0195, 0.0125, 11_000_000, 1_200_000),
            ("CCS_SEKUSD_18M", Period("18M"), 0.0220, 0.0130, 12_000_000, 1_250_000),
        ]
        for name, tenor, pay_rate, receive_rate, sek_nominal, usd_nominal in ccs_specs:
            issue_date = as_of
            maturity = issue_date + tenor
            sek_leg = FixedLeg(
                nominal=sek_nominal,
                currency="SEK",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("6M"),
                calendar=target,
                day_counter=dc365,
                rate=pay_rate,
            )
            usd_leg = FixedLeg(
                nominal=usd_nominal,
                currency="USD",
                issue_date=issue_date,
                maturity=maturity,
                tenor=Period("3M"),
                calendar=target,
                day_counter=dc365,
                rate=receive_rate,
            )
            positions.append(
                Position(
                    name,
                    CrossCurrencySwap(
                        paying_leg=sek_leg,
                        receiving_leg=usd_leg,
                        discount_curves={
                            "SEK": context.discount["SEK"],
                            "USD": context.discount["USD"],
                        },
                        fx_spot=context.fx_spot[("SEK", "USD")],
                        fx_forward_points=fx_points(),
                        pricing_currency="SEK",
                    ),
                )
            )

    return Portfolio(positions)


@pytest.fixture()
def scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="rates_up_25bp",
            instructions=[ScenarioInstruction(target="discount", key="SEK", shift=0.0025, relative=False)],
        ),
        Scenario(
            name="vol_up",
            instructions=[ScenarioInstruction(target="vols", key="OMX_ATM", shift=0.05, relative=True)],
        ),
        Scenario(
            name="usdsek_up_2pct",
            instructions=[ScenarioInstruction(target="fx_spot", key=("SEK", "USD"), shift=0.02, relative=True)],
        ),
    ]


def test_risk_engine_matches_manual_revaluation(
    monkeypatch, context: MarketContext, portfolio: Portfolio, scenarios: list[Scenario]
) -> None:
    def _market_context_deepcopy(self: MarketContext, memo: dict | None = None) -> MarketContext:
        return self.copy()

    monkeypatch.setattr(MarketContext, "__deepcopy__", _market_context_deepcopy, raising=False)
    engine = RiskEngine(context=context, portfolio=portfolio, scenarios=scenarios)
    results = engine.run_all()
    base_total = results[0].total_pv
    assert results[0].name == "Base"
    # Manual scenario application
    for scenario in scenarios:
        stress_ctx = context.copy()
        scenario.apply(context, stress_ctx)
        manual_total = portfolio.price(stress_ctx)
        scenario_result = next(r for r in results if r.name == scenario.name)
        assert scenario_result.total_pv == pytest.approx(manual_total)
        assert scenario_result.delta_vs_base == pytest.approx(manual_total - base_total)
