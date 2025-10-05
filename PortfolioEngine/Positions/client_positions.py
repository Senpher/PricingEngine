from abc import ABC, abstractmethod


class ClientPosition(ABC):
    @abstractmethod
    def value_position(self) -> float:
        pass  # Here could make use of e.g. QuantLib for valuation

    def set_up_position(self) -> None:
        # Called after applying risk factors to calibrate position
        # e.g. (re)calculate z-spread for bonds to match dirty price.
        pass

    def increment_value_date(self, days_to_add: int) -> None:
        pass

    def get_pos_name(self) -> str:
        pass

    def get_pos_currency(self) -> str:
        pass

    def update_risk_factors(self, risk_factor_list: dict) -> None:
        pass

    def get_pos_type(self) -> str:
        pass

    def get_nominal(self) -> float:
        pass

    def get_calibrated_spread(self) -> float:
        pass

    def get_used_risk_factor_dict(self) -> dict:
        pass
