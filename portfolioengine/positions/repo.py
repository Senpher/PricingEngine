from QuantLib import (
    Date,
)
from datetime import date

from .client_positions import ClientPosition
from ..data_structures.ql_mapping import (
    QlDayCountMapper,
    ql_eval_date,
)


class Repo(ClientPosition):
    def __init__(
        self,
        ccy: str,
        value_date: str,
        issue_date: str,
        initial_cash_amount: float,
        repo_rate: float,
        day_count: str,
        maturity: date,
        underlying_nominal: float,
        underlying_dirty_price: float,
        hair_cut: float,
        pos_name: str = None,
    ):
        # Initialize and convert to QL types where needed
        self.posName = pos_name
        self.ccy = ccy
        self.initial_cash_amount = initial_cash_amount
        self.repo_rate = repo_rate
        self.underlying_nominal = underlying_nominal
        self.underlying_dirty_price = underlying_dirty_price
        self.hair_cut = hair_cut
        self.ql_day_count = QlDayCountMapper[day_count].value

        self.valueDate = (
            date.fromisoformat(value_date) if not isinstance(value_date, date) else value_date
        )  # input dates as e.g. "2024-02-13" and convert in instantiation
        self.ql_value_date = Date(self.valueDate.day, self.valueDate.month, self.valueDate.year)

        self.maturity = (
            date.fromisoformat(maturity) if not isinstance(maturity, date) else maturity
        )  # input dates as e.g. "2024-02-13" and convert in instantiation
        self.cash_flows = None  # initialize and fill with used market data / debug info
        self.issue_date = (
            date.fromisoformat(issue_date) if not isinstance(issue_date, date) else issue_date
        )  # input dates as e.g. "2024-02-13" and convert in instantiation
        self.ql_issue_date = Date(self.issue_date.day, self.issue_date.month, self.issue_date.year)

    def valuePosition(
        self,
    ) -> float:  # Risk neutral PV calc for risk. Unrelated to MTM of Repo for PCS
        return 0

    def getUsedRiskFactorDict(self) -> dict:
        pass

    def MTM(self) -> tuple[float, dict, str]:  # "MTM" calc for PCS collateralization
        with ql_eval_date(self.ql_value_date):  # Sets the global evaluation date
            accrual_fraction = self.ql_day_count.yearFraction(self.ql_issue_date, self.ql_value_date)
            accrued_interest = self.initial_cash_amount * self.repo_rate * accrual_fraction
            cash_value = self.initial_cash_amount + accrued_interest
            collateral_value = (self.underlying_dirty_price / 100.0) * self.underlying_nominal * (1 - self.hair_cut)
            mtm = cash_value - collateral_value
            used_risk_factors = {
                "initial_cash_amount": self.initial_cash_amount,
                "accrued_interest": accrued_interest,
                "cash_value": cash_value,
                "dirty_price": self.underlying_dirty_price,
                "bond_nominal": self.underlying_nominal,
                "hair_cut": self.hair_cut,
                "collateral_value": collateral_value,
            }

            # used_risk_factors = self.getUsedRiskFactorDict()
            warning_message = None
        return (mtm, used_risk_factors, warning_message)
