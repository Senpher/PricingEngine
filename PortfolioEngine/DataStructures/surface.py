import numpy as np
from QuantLib import Period, Date, DayCounter, BlackVarianceSurface, TARGET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class SurfaceData:
    # Created at input
    surfaceName: str
    seriesNames: list[str]
    maturities: np.ndarray
    moneyness: np.ndarray
    seriesValues: np.ndarray
    ql_tenors: list[Period]
    # Derived parameter from init_surface (dependent on strike, value date etc.)
    ql_maturities: list[Date] = None
    ql_ref_date: Date = None
    ql_dayCounter: DayCounter = None
    # Surface indexing
    mny_levels: Optional[List[float]] = None
    mat_axis: Optional[List[Date]] = None
    grid_positions: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    vol_grid: Optional[List[List[float]]] = None

    def init_surface(self, ref_date: Date, ql_day_counter: DayCounter):
        # Init values and ql_maturities from the reference date.
        # We deliberately avoid initializing absolute strikes; the volatility
        # surface works with "sticky moneyness" rather than "sticky strikes".
        self.ql_dayCounter = ql_day_counter
        self.ql_ref_date = ref_date
        # Build canonical maturity axis (strictly increasing) and moneyness axis (unique + sorted). Pre-compute indexing
        # Maturity
        self.ql_maturities = [ref_date + t for t in self.ql_tenors]
        self.mat_axis = sorted(set(self.ql_maturities))  # list[Date], unique
        # Moneyness
        all_m = np.asarray(self.moneyness, dtype=float)
        self.mny_levels = sorted(np.unique(all_m).tolist())
        mny_index = {m: j for j, m in enumerate(self.mny_levels)}
        mat_index = {d: i for i, d in enumerate(self.mat_axis)}

        # Build a 2D baseline grid of the vol surface (rows = moneyness j, cols = maturities i)
        j, i_ = len(self.mny_levels), len(self.mat_axis)
        grid = [[0.0 for _ in range(i_)] for _ in range(j)]
        n = len(self.seriesNames)
        assert (
            len(self.maturities) == n and len(self.moneyness) == n and len(self.seriesValues) == n
        )  # Check consistency
        for k in range(n):
            d = self.ql_maturities[k]
            m = float(self.moneyness[k])
            j = mny_index[m]
            i = mat_index[d]
            grid[j][i] = float(self.seriesValues[k])
        self.vol_grid = grid

        # Keep track of which name corresponds to which moneyness+maturity for easy updating for risk (need seriesName)
        self.grid_positions.clear()
        if self.seriesNames is not None and all(n is not None for n in self.seriesNames):
            names = list(self.seriesNames)
            if len(set(names)) == len(names):
                for k, name in enumerate(names):
                    d = self.ql_maturities[k]
                    m = float(self.moneyness[k])
                    self.grid_positions[name] = (mny_index[m], mat_index[d])

    def ql_surface(  # Create a surface from the vol grid. Updating it before if riskFactorDict provided.
        self, spot_rate: float, risk_factor_dict: Optional[dict] = None
    ) -> BlackVarianceSurface:
        grid = [row[:] for row in self.vol_grid]
        if risk_factor_dict:
            get = risk_factor_dict.get
            for name, (r, c) in self.grid_positions.items():
                v = get(name)
                if v is not None:
                    grid[r][c] = float(v)

        strikes = [
            float(spot_rate) / m for m in self.mny_levels
        ]  # Re-calculate the absolute strikes of surface with the (stressed) spot rate
        # Assure increasing strikes by QL convention
        # Moneyness : AHS data is spot/strike=moneynesss so we sort ascending by mn
        perm = sorted(range(len(strikes)), key=lambda i: strikes[i])  # ascending by strike
        strikes_sorted = [strikes[i] for i in perm]
        grid_sorted = [grid[i] for i in perm]  # reorder rows the same way

        surf = BlackVarianceSurface(
            self.ql_ref_date,
            TARGET(),
            list(self.mat_axis),  # columns
            list(strikes_sorted),  # rows
            grid_sorted,  # J x I list-of-lists (floats)
            self.ql_dayCounter,
        )
        return surf
