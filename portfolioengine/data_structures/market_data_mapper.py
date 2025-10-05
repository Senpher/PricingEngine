import numpy as np
from QuantLib import Period, Days, Weeks, Months, Years
from dataclasses import dataclass, field
from typing import Optional

from portfolioengine.data_structures import CurveData, SurfaceData


@dataclass
class MarketDataMapper:
    curveDataMapping: dict[str, CurveData] = field(default_factory=dict)
    surfaceDataMapping: dict[str, SurfaceData] = field(default_factory=dict)

    def add_curve_data(
        self,
        curve_name: str,
        series_names: list[str] = None,
        maturities: np.ndarray = None,
        tenors: list[str] = None,
        series_values: np.ndarray = None,
    ) -> None:  # Can add validation error if not same length of arrays/lists
        if series_names is None:  # create dummy array of length of either mat or tenor if no names are given.
            tenor_len = len(tenors) if tenors is not None else 0
            maturities_len = len(maturities) if maturities is not None else 0
            series_names = np.empty(max(tenor_len, maturities_len))

        if series_values is None:
            series_values = np.empty(len(series_names))  # set to empty array of same length of no values added (default)
        else:
            series_values = np.array(series_values)  # Convert to np.array if passed as list

        if maturities is None:
            maturities = np.empty(len(series_names))  # set to empty array of same length of no values added (default)
        ql_maturities = np.empty(
            len(series_names)
        )  # Always set to empty and created with value date and tenors when setting up position
        ql_tenors = [None] * len(series_names)
        if tenors[0] is not None:  # assuming all are None or none are
            for i, tenor in enumerate(tenors):
                # Parse the tenor string
                period = Period()
                if tenor.endswith("D"):
                    period = Period(int(tenor[:-1]), Days)
                elif tenor.endswith("W"):
                    period = Period(int(tenor[:-1]), Weeks)
                elif tenor.endswith("M"):
                    period = Period(int(tenor[:-1]), Months)
                elif tenor.endswith("Y"):
                    period = Period(int(tenor[:-1]), Years)
                ql_tenors[i] = period
        else:
            ql_tenors = np.empty(
                len(series_names)
            )  # Set to empty if not specified (and use numerical maturities instead)

        # Sort by ql_tenors
        # Create (index, ql_tenor) pairs, sort by tenor, then extract indices
        indexed_tenors = [(i, tenor) for i, tenor in enumerate(ql_tenors)]
        indexed_tenors.sort(key=lambda x: x[1])  # Sort by Period objects
        sorted_indices = [idx for idx, _ in indexed_tenors]
        # Sort arrays by maturities in ascending order before creating CurveData object
        series_names = [series_names[i] for i in sorted_indices]
        series_values = series_values[sorted_indices]
        ql_tenors = [ql_tenors[i] for i in sorted_indices]  # Keep as list for QuantLib objects
        # maturities = maturities[sortedIndices]

        curve_data = CurveData(
            curveName=curve_name,
            seriesNames=series_names,
            maturities=maturities,
            seriesValues=series_values,
            ql_tenors=ql_tenors,
            ql_maturities=ql_maturities,
        )
        self.curveDataMapping[curve_name] = curve_data

    def add_surface_data(
        self,
        surface_name: str,
        series_names: list[str] = None,
        maturities: np.ndarray = None,
        strikes: np.ndarray = None,  # moneyness
        tenors: list[str] = None,
        series_values: np.ndarray = None,
    ) -> None:
        # Create dummy array of length of either mat or tenor if no names are given
        if series_names is None:
            tenor_len = len(tenors) if tenors is not None else 0
            maturities_len = len(maturities) if maturities is not None else 0
            strikes_len = len(strikes) if strikes is not None else 0
            max_len = max(tenor_len, maturities_len, strikes_len)
            series_names = np.empty(max_len, dtype=object)

        if series_values is None:
            series_values = np.empty(len(series_names))
        else:
            series_values = np.array(series_values)  # Convert to np.array if passed as list

        if maturities is None:
            maturities = np.empty(len(series_names))

        if strikes is None:
            strikes = np.empty(len(series_names))

        # Always set to empty and created with value date and tenors when setting up position
        ql_maturities = np.empty(len(series_names), dtype=object)
        ql_tenors = [None] * len(series_names)

        # Parse tenors if provided
        if tenors is not None and tenors[0] is not None:  # assuming all are None or none are
            for i, tenor in enumerate(tenors):
                # Parse the tenor string
                if tenor.endswith("D"):
                    period = Period(int(tenor[:-1]), Days)
                elif tenor.endswith("W"):
                    period = Period(int(tenor[:-1]), Weeks)
                elif tenor.endswith("M"):
                    period = Period(int(tenor[:-1]), Months)
                elif tenor.endswith("Y"):
                    period = Period(int(tenor[:-1]), Years)
                ql_tenors[i] = period
        else:
            ql_tenors = np.empty(len(series_names), dtype=object)

        # TODO: Add matrix support once the value date conversion logic is in
        # place (required for building ql_maturities on demand).

        surface_data = SurfaceData(
            surfaceName=surface_name,
            seriesNames=series_names,
            maturities=maturities,
            moneyness=strikes,
            seriesValues=series_values,
            ql_tenors=ql_tenors,
            ql_maturities=ql_maturities,
        )
        self.surfaceDataMapping[surface_name] = surface_data

    def get_curve_data(self, curve_name: str) -> Optional[CurveData]:
        return self.curveDataMapping.get(curve_name, None)

    def get_surface_data(self, surface_name: str) -> Optional[SurfaceData]:
        return self.surfaceDataMapping.get(surface_name, None)
