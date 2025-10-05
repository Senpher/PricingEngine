from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List
import numpy as np
import QuantLib as ql
from pricingengine.termstructures.curve import Curve


@dataclass
class CurveData:
    # Created at input
    curveName: str
    seriesNames: list[str]
    maturities: np.ndarray  # Not used if we have ql_tenors
    seriesValues: np.ndarray
    ql_tenors: list[ql.Period]
    # derived at init_curve
    ql_ref_date: Optional[ql.Date] = None
    ql_day_count: Optional[ql.DayCounter] = None
    ql_maturities: Optional[List[ql.Date]] = None  # Strictly increasing dates
    # indexing
    name_to_idx: Dict[str, int] = field(default_factory=dict)

    def init_curve(self, ref_date: ql.Date, day_count: ql.DayCounter) -> None:
        # Init values and maturities
        self.ql_day_count = day_count
        self.ql_ref_date = ref_date
        self.ql_maturities = [ref_date + t for t in self.ql_tenors]
        # 1D index map for updating
        self.name_to_idx = {name: i for i, name in enumerate(self.seriesNames)}

    def ql_ZeroCurve(self, riskFactorDict: Optional[dict] = None) -> ql.ZeroCurve:
        rates = self.seriesValues.copy()
        if riskFactorDict:
            get = riskFactorDict.get
            for name, i in self.name_to_idx.items():
                v = get(name)
                if v is not None:
                    rates[i] = float(v)

        return ql.ZeroCurve(list(self.ql_maturities), rates.tolist(), self.ql_day_count)

    def PE_Curve(
        self, ql_value_date: ql.Date, ql_daycount
    ):  ### Add creating of QL Curve here maybe? To fetch it. Maybe directly ZeroCurve etc. as well as needed?
        ql_maturities = [ql_value_date + tenor for tenor in self.ql_tenors]
        yield_curve = Curve(  # NOTE: Curve is Pricing Engine Object
            dates=ql_maturities,
            day_counter=ql_daycount,
            quotes=tuple(self.seriesValues),
        )
        return yield_curve


@dataclass
class SurfaceData:
    # Created at input
    surfaceName: str
    seriesNames: list[str]
    maturities: np.ndarray
    moneyness: np.ndarray
    seriesValues: np.ndarray
    ql_tenors: list[ql.Period]
    # Derived parameter from init_surface (dependent on strike, value date etc.)
    ql_maturities: list[ql.Date] = None
    ql_ref_date: ql.Date = None
    ql_dayCounter: ql.DayCounter = None
    # Surface indexing
    mny_levels: Optional[List[float]] = None
    mat_axis: Optional[List[ql.Date]] = None
    grid_positions: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    vol_grid: Optional[List[List[float]]] = None

    def init_surface(self, ref_date: ql.Date, ql_dayCounter: ql.DayCounter):
        # Init values and ql_marturities from the reference date. note that we can't initialize absolute strikes, as we want "sticky moneyness" not "sticky strikes"
        self.ql_dayCounter = ql_dayCounter
        self.ql_ref_date = ref_date
        # Build canonical maturity axis (strictly increasing) and moneyness axis (unique + sorted). Pre-compute indexing
        # Maturity
        self.ql_maturities = [ref_date + t for t in self.ql_tenors]
        self.mat_axis = sorted(set(self.ql_maturities))  # list[ql.Date], unique
        # Moneyness
        all_m = np.asarray(self.moneyness, dtype=float)
        self.mny_levels = sorted(np.unique(all_m).tolist())
        mny_index = {m: j for j, m in enumerate(self.mny_levels)}
        mat_index = {d: i for i, d in enumerate(self.mat_axis)}

        # Build a 2D baseline grid of the vol surface (rows = moneyness j, cols = maturities i)
        J, I_ = len(self.mny_levels), len(self.mat_axis)
        grid = [[0.0 for _ in range(I_)] for _ in range(J)]
        N = len(self.seriesNames)
        assert (
            len(self.maturities) == N
            and len(self.moneyness) == N
            and len(self.seriesValues) == N
        )  # Check consistency
        for k in range(N):
            d = self.ql_maturities[k]
            m = float(self.moneyness[k])
            j = mny_index[m]
            i = mat_index[d]
            grid[j][i] = float(self.seriesValues[k])
        self.vol_grid = grid

        # Keep track of which name corresponds to which moneyness+maturity for easy updating for risk (need seriesName)
        self.grid_positions.clear()
        if self.seriesNames is not None and all(
            n is not None for n in self.seriesNames
        ):
            names = list(self.seriesNames)
            if len(set(names)) == len(names):
                for k, name in enumerate(names):
                    d = self.ql_maturities[k]
                    m = float(self.moneyness[k])
                    self.grid_positions[name] = (mny_index[m], mat_index[d])

    def ql_surface(  # Create a surface from the vol grid. Updating it before if riskFactorDict provided.
        self, spot_rate: float, riskFactorDict: Optional[dict] = None
    ) -> ql.BlackVarianceSurface:
        grid = [row[:] for row in self.vol_grid]
        if riskFactorDict:
            get = riskFactorDict.get
            for name, (r, c) in self.grid_positions.items():
                v = get(name)
                if v is not None:
                    grid[r][c] = float(v)

        strikes = [
            float(spot_rate) / m for m in self.mny_levels
        ]  # Re-calculate the absolute strikes of surface with the (stressed) spot rate
        # Assure increasing strikes by QL convention
        # Moneyness : AHS data is spot/strike=moneynesss so we sort ascending by mn
        perm = sorted(
            range(len(strikes)), key=lambda i: strikes[i]
        )  # ascending by strike
        strikes_sorted = [strikes[i] for i in perm]
        grid_sorted = [grid[i] for i in perm]  # reorder rows the same way

        surf = ql.BlackVarianceSurface(
            self.ql_ref_date,
            ql.TARGET(),
            list(self.mat_axis),  # columns
            list(strikes_sorted),  # rows
            grid_sorted,  # J x I list-of-lists (floats)
            self.ql_dayCounter,
        )
        return surf


@dataclass
class MarketDataMapper:
    curveDataMapping: dict[str, CurveData] = field(default_factory=dict)
    surfaceDataMapping: dict[str, SurfaceData] = field(default_factory=dict)

    def addCurveData(
        self,
        curveName: str,
        seriesNames: list[str] = None,
        maturities: np.ndarray = None,
        tenors: list[str] = None,
        seriesValues: np.ndarray = None,
    ) -> None:  # Can add validation error if not same length of arrays/lists
        if (
            seriesNames is None
        ):  # create dummy array of length of either mat or tenor if no names are given.
            tenor_len = len(tenors) if tenors is not None else 0
            maturities_len = len(maturities) if maturities is not None else 0
            seriesNames = np.empty(max(tenor_len, maturities_len))

        if seriesValues is None:
            seriesValues = np.empty(
                len(seriesNames)
            )  # set to empty array of same length of no values added (default)
        else:
            seriesValues = np.array(
                seriesValues
            )  # Convert to np.array if passed as list

        if maturities is None:
            maturities = np.empty(
                len(seriesNames)
            )  # set to empty array of same length of no values added (default)
        ql_maturities = np.empty(
            len(seriesNames)
        )  # Always set to empty and created with value date and tenors when setting up position
        ql_tenors = [None] * len(seriesNames)
        if tenors[0] is not None:  # assuming all are None or none are
            for i, tenor in enumerate(tenors):
                # Parse the tenor string
                if tenor.endswith("D"):
                    period = ql.Period(int(tenor[:-1]), ql.Days)
                elif tenor.endswith("W"):
                    period = ql.Period(int(tenor[:-1]), ql.Weeks)
                elif tenor.endswith("M"):
                    period = ql.Period(int(tenor[:-1]), ql.Months)
                elif tenor.endswith("Y"):
                    period = ql.Period(int(tenor[:-1]), ql.Years)
                ql_tenors[i] = period
        else:
            ql_tenors = np.empty(
                len(seriesNames)
            )  # Set to empty if not specified (and use numerical maturities instead)

        # Sort by ql_tenors
        # Create (index, ql_tenor) pairs, sort by tenor, then extract indices
        indexed_tenors = [(i, tenor) for i, tenor in enumerate(ql_tenors)]
        indexed_tenors.sort(key=lambda x: x[1])  # Sort by Period objects
        sortedIndices = [idx for idx, _ in indexed_tenors]
        # Sort arrays by maturities in ascending order before creating CurveData object
        seriesNames = [seriesNames[i] for i in sortedIndices]
        seriesValues = seriesValues[sortedIndices]
        ql_tenors = [
            ql_tenors[i] for i in sortedIndices
        ]  # Keep as list for QuantLib objects
        # maturities = maturities[sortedIndices]

        curveData = CurveData(
            curveName=curveName,
            seriesNames=seriesNames,
            maturities=maturities,
            seriesValues=seriesValues,
            ql_tenors=ql_tenors,
            ql_maturities=ql_maturities,
        )
        self.curveDataMapping[curveName] = curveData

    def addSurfaceData(
        self,
        surfaceName: str,
        seriesNames: list[str] = None,
        maturities: np.ndarray = None,
        strikes: np.ndarray = None,  # moneyness
        tenors: list[str] = None,
        seriesValues: np.ndarray = None,
    ) -> None:
        # Create dummy array of length of either mat or tenor if no names are given
        if seriesNames is None:
            tenor_len = len(tenors) if tenors is not None else 0
            maturities_len = len(maturities) if maturities is not None else 0
            strikes_len = len(strikes) if strikes is not None else 0
            max_len = max(tenor_len, maturities_len, strikes_len)
            seriesNames = np.empty(max_len, dtype=object)

        if seriesValues is None:
            seriesValues = np.empty(len(seriesNames))
        else:
            seriesValues = np.array(
                seriesValues
            )  # Convert to np.array if passed as list

        if maturities is None:
            maturities = np.empty(len(seriesNames))

        if strikes is None:
            strikes = np.empty(len(seriesNames))

        # Always set to empty and created with value date and tenors when setting up position
        ql_maturities = np.empty(len(seriesNames), dtype=object)
        ql_tenors = [None] * len(seriesNames)

        # Parse tenors if provided
        if (
            tenors is not None and tenors[0] is not None
        ):  # assuming all are None or none are
            for i, tenor in enumerate(tenors):
                # Parse the tenor string
                if tenor.endswith("D"):
                    period = ql.Period(int(tenor[:-1]), ql.Days)
                elif tenor.endswith("W"):
                    period = ql.Period(int(tenor[:-1]), ql.Weeks)
                elif tenor.endswith("M"):
                    period = ql.Period(int(tenor[:-1]), ql.Months)
                elif tenor.endswith("Y"):
                    period = ql.Period(int(tenor[:-1]), ql.Years)
                ql_tenors[i] = period
        else:
            ql_tenors = np.empty(len(seriesNames), dtype=object)

        # To do: Put Matrix stuff here (maybe - need value date then as well for converting ql_maturitie. Do we mind it here?)

        surfaceData = SurfaceData(
            surfaceName=surfaceName,
            seriesNames=seriesNames,
            maturities=maturities,
            moneyness=strikes,
            seriesValues=seriesValues,
            ql_tenors=ql_tenors,
            ql_maturities=ql_maturities,
        )
        self.surfaceDataMapping[surfaceName] = surfaceData

    def getCurveData(self, curveName: str) -> Optional[CurveData]:
        return self.curveDataMapping.get(curveName, None)

    def getSurfaceData(self, surfaceName: str) -> Optional[SurfaceData]:
        return self.surfaceDataMapping.get(surfaceName, None)
