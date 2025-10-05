from __future__ import annotations

from QuantLib import (
    EuropeanExercise,
    BermudanExercise,
    Swaption as QLSwaption,
    Settlement,
    BlackSwaptionEngine,
    BachelierSwaptionEngine,
    Date,
    HullWhite,
    TreeSwaptionEngine,
    Period,
    QuoteHandle,
    SimpleQuote,
    SwaptionHelper,
    LevenbergMarquardt,
    EndCriteria,
    ShiftedLognormal,
    Normal,
    BlackCalibrationHelper,
    SwaptionVolatilityStructureHandle,
    JamshidianSwaptionEngine,
    SwaptionVolatilityStructure,
    ModifiedFollowing,
    SwapIndex,
    Months,
    TimeGrid,
    Settings,
)
from dataclasses import dataclass
from typing import Optional, Sequence

from pricingengine.instruments.common import Instrument
from pricingengine.instruments.interest_rate_swap import InterestRateSwap


@dataclass(frozen=True, kw_only=True)
class Swaption(Instrument):
    """
    Vanilla swaption on a single-currency InterestRateSwap (payer or receiver).

    Parameters
    ----------
    irs : InterestRateSwap
        Underlying swap (index already bound; discount handle on irs).
    vol_surface : QuantLib.SwaptionVolatilityStructureHandle
        Volatility surface used by the pricing engine.
    expiries : sequence of QuantLib.Date | None
        One date -> European; multiple -> Bermudan. Defaults to [irs.issue_date].
    settlement : 'physical' | 'cash'
    is_long : bool
    vol_model : 'black' | 'bachelier'
        Choose engine explicitly.
    """

    irs: InterestRateSwap
    vol_surface: SwaptionVolatilityStructureHandle
    expiries: Optional[Sequence[Date]] = None
    settlement: str = "physical"
    vol_model: str = "bachelier"
    is_long: bool = True
    engine: str = "auto"  # "auto" | "surface" | "hw"

    # Hull–White (for Bermudans)
    hw_a: Optional[float] = None
    hw_sigma: Optional[float] = None
    hw_time_steps: int = 80
    time_grid: TimeGrid | None = None

    def __post_init__(self):
        # Important: when receiving a cube through a handle link, QL SWIG does not downcast to Cube class
        # But instead sends a vol structure handle, therefore it is impossible to enforce exact class match
        # Instead we enforce vol structure handle with required parameters
        if not isinstance(self.vol_surface, SwaptionVolatilityStructureHandle):
            raise TypeError("vol_surface must be a SwaptionVolatilityStructureHandle.")
        link = self.vol_surface.currentLink()
        if not isinstance(link, SwaptionVolatilityStructure):
            raise TypeError("vol_surface.currentLink() must be a SwaptionVolatilityStructure.")
        if self.settlement is None or self.settlement.lower() not in {
            "physical",
            "cash",
        }:
            raise ValueError("settlement must be 'physical' or 'cash'")
        if self.vol_model is None or self.vol_model.lower() not in {
            "black",
            "bachelier",
        }:
            raise ValueError("vol_model must be 'black' or 'bachelier'")

        self._validate_curve_horizon()

    # ---------- properties ----------
    @property
    def valuation_date(self) -> Date:
        # Always reflect the current global eval date
        return Settings.instance().evaluationDate

    @property
    def currency(self):
        return self.irs.currency

    @property
    def strike(self):
        # by convention, the swaption strike = underlying fixed coupon
        return self.irs.fixed_leg.rate

    def swaption_type(self) -> str:
        return "payer" if (self.irs.paying_leg is self.irs.fixed_leg) else "receiver"

    @property
    def expiry(self) -> Date:
        """First (or only) exercise date."""
        return self._expiries()[0]

    @property
    def is_expired(self) -> bool:
        return self.valuation_date > self.expiry

    # --- how long is the underlying swap (as a Period in months)?
    def _required_swap_len_period(self) -> Period:
        v = self.irs.vanilla()  # needed to keep other variable alive else C++ crash
        sch = v.fixedSchedule()
        start = sch.startDate()
        end = sch.endDate()
        months = 12 * (end.year() - start.year()) + (int(end.month()) - int(start.month()))
        if months <= 0:
            months = 1
        return Period(months, Months)

    # --- ensure fwd/discount curves cover [latest expiry .. swap end], or allow extrapolation
    def _validate_curve_horizon(self) -> None:
        idx = self.irs.floating_leg.index
        cal = idx.fixingCalendar()
        fwd = idx.forwardingTermStructure()
        dh = self.irs.discount_curve

        # latest exercise we’ll ever use for this instance
        latest_expiry = max(self._expiries())
        opt_date = cal.adjust(latest_expiry, ModifiedFollowing)

        swap_len = self._required_swap_len_period()
        end_needed = cal.advance(opt_date, swap_len, ModifiedFollowing)

        try:
            fwd_link = fwd.currentLink()
        except RuntimeError as e:
            raise ValueError("Index forwarding curve handle is empty or not set.") from e
        try:
            disc_link = dh.currentLink()
        except RuntimeError as e:
            raise ValueError("Discount curve handle is empty or not set.") from e

        fwd_allows = bool(fwd_link.allowsExtrapolation())
        if (end_needed > fwd_link.maxDate()) and (not fwd_allows):
            raise ValueError(
                f"Index forwarding curve too short: need ≥ {end_needed.ISO()}, "
                f"but maxDate is {fwd_link.maxDate().ISO()}. Enable extrapolation or extend pillars."
            )

        disc_allows = bool(disc_link.allowsExtrapolation())
        if (end_needed > disc_link.maxDate()) and (not disc_allows):
            raise ValueError(
                f"Discount curve too short: need ≥ {end_needed.ISO()}, "
                f"but maxDate is {disc_link.maxDate().ISO()}. Enable extrapolation or extend pillars."
            )

    # ---------- core helpers ----------
    def _expiries(self) -> Sequence[Date]:
        if self.expiries and len(self.expiries) > 0:
            return self.expiries
        # default to swap start (typical for swaptions)
        # NOTE: in practice you might want calendar.advance(irs.issue_date, -index.fixingDays(), ...)
        return [self.irs.issue_date]

    def _exercise_ql(self):
        exps = self._expiries()
        if len(exps) == 1:
            return EuropeanExercise(exps[0])
        else:
            return BermudanExercise(list(exps))

    def _settlement_ql(self):
        return Settlement.Physical if self.settlement.lower() == "physical" else Settlement.Cash

    def _engine_european(self):
        """
        Surface-based engine; respects chosen model.
        """
        dh = self.irs.discount_curve  # YieldTermStructureHandle
        if self.vol_model.lower() == "bachelier":
            return BachelierSwaptionEngine(dh, self.vol_surface)
        elif self.vol_model.lower() == "black":
            return BlackSwaptionEngine(dh, self.vol_surface)
        else:
            raise ValueError("vol_type must be 'black' or 'bachelier'")

    def _engine_bermudan(self):
        # Use provided params if given; otherwise calibrate to the surface
        if self.hw_a is None or self.hw_sigma is None:
            model = self._calibrate_hw()
        else:
            model = HullWhite(self.irs.discount_curve, float(self.hw_a), float(self.hw_sigma))

        if self.time_grid is not None:
            return TreeSwaptionEngine(model, self.time_grid, self.irs.discount_curve)
        else:
            return TreeSwaptionEngine(model, int(self.hw_time_steps), self.irs.discount_curve)

    def _use_tree(self) -> bool:
        if self.engine == "hw":
            return True
        if self.engine == "surface":
            return False
        return len(self._expiries()) > 1

    # --- option tenor -> option date (on index calendar) ---
    def _option_date_from_tenor(self, opt_tenor: Period) -> Date:
        idx = self.irs.floating_leg.index
        return idx.fixingCalendar().advance(self.valuation_date, opt_tenor, ModifiedFollowing)

    # --- detect cube-only API through capability check (SWIG won’t downcast) ---
    @staticmethod
    def _has_cube_api(surf: SwaptionVolatilityStructure) -> bool:
        return all(callable(getattr(surf, name, None)) for name in ("optionTenors", "swapTenors", "atmStrike", "shift"))

    def _atm_strike_for(self, opt_tenor: Period, swap_tenor: Period) -> float:
        """
        ATM = par fixed rate of the swap that starts on spot after the option date.
        We compute via SwapIndex.fixing(option_date).
        """
        surf = self.vol_surface.currentLink()
        if self._has_cube_api(surf):
            try:
                return float(surf.atmStrike(opt_tenor, swap_tenor))
            except (TypeError, AttributeError, RuntimeError, ValueError):
                pass  # fall back to SwapIndex route below

        idx = self.irs.floating_leg.index
        option_date = self._option_date_from_tenor(opt_tenor)
        fixed_dc = self.irs.fixed_leg.day_counter
        fixed_tenor = self.irs.fixed_leg.tenor
        s_idx = SwapIndex(
            "ATM",
            swap_tenor,
            idx.fixingDays(),
            idx.currency(),
            idx.fixingCalendar(),
            fixed_tenor,
            ModifiedFollowing,
            fixed_dc,
            idx,  # projection (forwarding TS)
            self.irs.discount_curve,  # discounting TS
        )
        option_date = idx.fixingCalendar().adjust(option_date, ModifiedFollowing)
        return float(s_idx.fixing(option_date))

    def _shift_for(self, opt_tenor: Period, swap_tenor: Period) -> float:
        surf = self.vol_surface.currentLink()
        # Try cube tenor-based first, then fallback to date-based shift if present.
        if hasattr(surf, "shift"):
            try:
                return float(surf.shift(opt_tenor, swap_tenor))  # cube-style
            except TypeError:
                try:
                    od = self._option_date_from_tenor(opt_tenor)
                    return float(surf.shift(od, swap_tenor))  # base-style
                except (TypeError, AttributeError, RuntimeError, ValueError):
                    pass  # no shift method on surface must imply no shift
        return 0.0

    def _surface_eval(self, opt_tenor: Period, swap_tenor: Period, strike: float, vt) -> float:
        """
        Get vol safely from surface/cube:
          * If cube API is visible, try (tenor, tenor, strike, voltype, shift).
          * Otherwise use date-based overload (Date start, Period length, Rate [,bool extrapolate]).
        """
        surf = self.vol_surface.currentLink()
        od = self._option_date_from_tenor(opt_tenor)

        # Try cube-style first (works only if SWIG exposes those methods)
        if self._has_cube_api(surf):
            try:
                sh = self._shift_for(opt_tenor, swap_tenor)
                return float(surf.volatility(opt_tenor, swap_tenor, strike, vt, sh))
            except TypeError:
                pass  # fall back to date-based

        # Date-based (available on all SwaptionVolatilityStructure)
        try:
            return float(surf.volatility(od, swap_tenor, strike, True))
        except TypeError:
            return float(surf.volatility(od, swap_tenor, strike))

    def _calibrate_hw(self) -> HullWhite:
        """
        Calibrate a Hull–White model (a, sigma) to a small basket of
        European swaptions sampled from the given vol surface.
        """
        dc_fix = self.irs.fixed_leg.day_counter
        dc_flt = self.irs.floating_leg.day_counter
        idx = self.irs.floating_leg.index
        dh = self.irs.discount_curve
        fixed_tenor = self.irs.fixed_leg.tenor

        surf = self.vol_surface.currentLink()

        # Build a small representative basket
        basket: list[tuple[Period, Period]] = []
        # Comment on tenors:
        # On Windows, when you call handle.currentLink(), SWIG returns a base-class proxy.
        # In that case those grid methods are not visible in Python even if the underlying C++ object is a cube/matrix.
        # So you can’t “see” the basket through that proxy.
        if self._has_cube_api(surf):
            try:
                opt_grid = list(surf.optionTenors())
                swap_grid = list(surf.swapTenors())
                if opt_grid and swap_grid:
                    basket.append((opt_grid[0], swap_grid[0]))
                    if len(opt_grid) > 1 and len(swap_grid) > 1:
                        basket.append((opt_grid[1], swap_grid[1]))
                    if len(opt_grid) > 2 and len(swap_grid) > 2:
                        basket.append((opt_grid[2], swap_grid[2]))
            except (AttributeError, TypeError, RuntimeError):
                basket = []
        if not basket:
            st = self._required_swap_len_period()  # swap tenor of the underlying (in months → Period)
            basket = [(Period("6M"), st), (Period("1Y"), st), (Period("2Y"), st)]
            if hasattr(surf, "enableExtrapolation"):
                try:
                    surf.enableExtrapolation()
                except (AttributeError, TypeError, RuntimeError):
                    pass

        vt = Normal if self.vol_model.lower() == "bachelier" else ShiftedLognormal
        model = HullWhite(dh)
        engine = JamshidianSwaptionEngine(model)
        helpers = []

        for opt_tenor, swap_tenor in basket:
            """
            Pulls an ATM vol from the surface. Why calibrate to ATM vs near underlying strike?
            One-factor HW can’t fit smiles across strikes. Industry practice is to calibrate HW to ATM (a/b σ) because:
                More stable across time.
                Matches the belly of the smile where most activity is.
            If you care about accuracy around a specific moneyness, you can calibrate using quotes near your strike(s). 
            Expect:
                Better local fit near those strikes.
                Worse fit elsewhere and potentially less stability day-to-day.
            """
            k_atm = self._atm_strike_for(opt_tenor, swap_tenor)  # robust route
            vol = self._surface_eval(opt_tenor, swap_tenor, k_atm, vt)
            shift = self._shift_for(opt_tenor, swap_tenor)
            q = QuoteHandle(SimpleQuote(vol))
            # Only works with positional arguments
            h = SwaptionHelper(
                opt_tenor,  # maturity (option tenor)
                swap_tenor,  # length (swap tenor)
                q,  # QuoteHandle(vol)
                idx,  # IborIndex
                fixed_tenor,  # fixed leg tenor
                dc_fix,  # fixed leg day counter
                dc_flt,  # float leg day counter
                dh,  # discount curve
                BlackCalibrationHelper.RelativePriceError,  # error type
                k_atm,  # strike -> Null => ATM
                1.0,  # nominal
                vt,  # VolatilityType (Normal or ShiftedLognormal)
                shift,  # shift
                # (leave settlementDays and averagingMethod at defaults)
            )
            h.setPricingEngine(engine)
            helpers.append(h)

        method = LevenbergMarquardt()
        end = EndCriteria(
            maxIteration=5000,
            maxStationaryStateIterations=50,
            rootEpsilon=1e-12,
            functionEpsilon=1e-12,
            gradientNormEpsilon=1e-12,
        )
        model.calibrate(helpers, method, end)
        return model

    def _swaption_ql(self) -> QLSwaption:
        ex = self._exercise_ql()
        swaption = QLSwaption(self.irs.vanilla(), ex, self._settlement_ql())

        if self._use_tree():
            swaption.setPricingEngine(self._engine_bermudan())
        else:
            swaption.setPricingEngine(self._engine_european())
        return swaption

    # ---------- public API ----------
    def npv(self) -> float:
        if self.is_expired:
            return 0.0
        npv = float(self._swaption_ql().NPV())
        return npv if self.is_long else -npv

    def implied_volatility(
        self,
        target_npv: float,
        accuracy: float = 1e-7,
        max_evaluations: int = 500,
        min_vol: float = 1e-6,
        max_vol: float = 5.0,
    ) -> float:
        """
        Scalar implied vol consistent with the chosen model.
        Uses the standard constant-vol inversion (no need to set an engine).
        """
        if self.is_expired:
            return 0.0

        # Build the payoff vanilla (with strike if provided)
        v = self.irs.vanilla()
        swaption = QLSwaption(v, self._exercise_ql(), self._settlement_ql())

        # Exact whole-month swap length from the underlying vanilla schedule
        sch = v.fixedSchedule()
        start, end = sch.startDate(), sch.endDate()
        months = 12 * (end.year() - start.year()) + (int(end.month()) - int(start.month()))
        if months <= 0:
            months = 1
        swap_len = Period(months, Months)

        # ATM strike of the spot-starting swap observed at option_date (multi-curve: index proj + IRS discount)
        option_date = self.expiry
        idx = self.irs.floating_leg.index
        dh = self.irs.discount_curve
        fixed_dc = self.irs.fixed_leg.day_counter
        fixed_tenor = self.irs.fixed_leg.tenor
        s_idx = SwapIndex(
            "ATM",
            swap_len,
            idx.fixingDays(),
            idx.currency(),
            idx.fixingCalendar(),
            fixed_tenor,
            ModifiedFollowing,
            fixed_dc,
            idx,  # projection curve = index forwarding TS
            dh,  # discounting curve = IRS discount TS
        )
        # Ensure business day on the index calendar
        option_date = idx.fixingCalendar().adjust(option_date, ModifiedFollowing)
        k_atm = float(s_idx.fixing(option_date))

        # Seed from surface at (option_date, swap_len, k_atm); fall back to 1%
        surf = self.vol_surface.currentLink()
        seed = 0.01
        try:
            # date-based: volatility(Date start, Period length, Rate strike, [bool extrapolate])
            try:
                seed = float(surf.volatility(option_date, swap_len, k_atm, True))
            except TypeError:
                seed = float(surf.volatility(option_date, swap_len, k_atm))
        except (TypeError, ValueError, AttributeError):
            pass  # staying with 1% seed

        vol_type = Normal if self.vol_model.lower() == "bachelier" else ShiftedLognormal
        shift = 0.0
        if vol_type is ShiftedLognormal:
            try:
                shift = float(surf.shift(option_date, swap_len))
            except (TypeError, ValueError, AttributeError):
                shift = 0.0

        vol = swaption.impliedVolatility(
            float(target_npv),
            self.irs.discount_curve,  # discounting used by the inversion
            float(seed),  # numeric seed (Volatility)
            float(accuracy),  # accuracy
            int(max_evaluations),  # maxEvaluations
            float(min_vol),
            float(max_vol),  # minVol, maxVol
            vol_type,
            float(shift),
        )

        return float(vol)

    def atm_strike(self) -> float:
        return float(self.irs.vanilla().fairRate())
