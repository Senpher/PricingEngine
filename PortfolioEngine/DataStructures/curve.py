from dataclasses import dataclass, field

import numpy as np
from QuantLib import Date, DayCounter, Period, ZeroCurve


@dataclass
class CurveData:
    # Created at input
    curveName: str
    seriesNames: list[str]
    maturities: np.ndarray  # Not used if we have ql_tenors
    seriesValues: np.ndarray
    ql_tenors: list[Period]
    # derived at init_curve
    ql_ref_date: Date | None = None
    ql_day_count: DayCounter | None = None
    ql_maturities: list[Date] | None = None  # Strictly increasing dates
    # indexing
    name_to_idx: dict[str, int] = field(default_factory=dict)

    def init_curve(self, ref_date: Date, day_count: DayCounter) -> None:
        # Init values and maturities
        self.ql_day_count = day_count
        self.ql_ref_date = ref_date
        self.ql_maturities = [ref_date + t for t in self.ql_tenors]
        # 1D index map for updating
        self.name_to_idx = {name: i for i, name in enumerate(self.seriesNames)}

    def ql_zero_curve(self, risk_factor_dict: dict | None = None) -> ZeroCurve:
        rates = self.seriesValues.copy()
        if risk_factor_dict:
            get = risk_factor_dict.get
            for name, i in self.name_to_idx.items():
                v = get(name)
                if v is not None:
                    rates[i] = float(v)

        return ZeroCurve(list(self.ql_maturities), rates.tolist(), self.ql_day_count)
