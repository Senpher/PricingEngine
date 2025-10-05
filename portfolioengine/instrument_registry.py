from enum import Enum

from .positions import (
    IRS,
    EquityOption,
    FXForward,
    FXOption,
    Repo,
)


class MetricFunction(Enum):
    MTM = "MTM"
    # DELTA = ... etc.


class InstrumentTypeToClass(Enum):
    FXForward = FXForward
    IRS = IRS
    Repo = Repo
    EquityOption = EquityOption
    FXOption = FXOption


def get_instrument_class(class_name):
    instrument_class = InstrumentTypeToClass[class_name].value
    if isinstance(instrument_class, type):
        return instrument_class
    else:
        return None


def get_metric_function(metric_name):
    try:
        function_name = MetricFunction[metric_name].value
    except KeyError:
        raise ValueError(f"Unknown metric: {metric_name}")
    return function_name
