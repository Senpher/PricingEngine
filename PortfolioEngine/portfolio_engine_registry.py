from enum import Enum

from RiskEngine.risk_engine_interface import InitializeRiskEngine


class EngineMetricFunction(Enum):
    VaR = "get_portfolio_var"


class PortfolioMetricToEngineClass(Enum):
    VaR = InitializeRiskEngine


def get_engine_class(class_name):
    engine_class = PortfolioMetricToEngineClass[class_name].value
    if isinstance(engine_class, type):
        return engine_class
    return None


def get_engine_metric_function(metric_name):
    try:
        function_name = EngineMetricFunction[metric_name].value
    except KeyError as err:
        raise ValueError(f"Unknown metric: {metric_name}") from err
    return function_name
