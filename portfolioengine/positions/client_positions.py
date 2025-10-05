from abc import ABC, abstractmethod


class ClientPosition(ABC):
    @abstractmethod
    def valuePosition(self) -> float:
        pass  # Here could make use of e.g. QuantLib for valuation

    def setUpPosition(self) -> None:
        # Called after applying risk factors to calibrate position
        # e.g. (re)calculate z-spread for bonds to match dirty price.
        pass

    def incrementValueDate(self, daysToAdd: int) -> None:
        pass

    def getPosName(self) -> str:
        pass

    def getPosCurrency(self) -> str:
        pass

    def updateRiskFactors(self, riskFactorList: dict) -> None:
        pass

    def getPosType(self) -> str:
        pass

    def getNominal(self) -> float:
        pass

    def getCalibratedSpread(self) -> float:
        pass

    def getUsedRiskFactorDict(self) -> dict:
        pass
