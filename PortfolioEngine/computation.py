from typing import Any

from .instrument_registry import (
    get_instrument_class,
    get_metric_function,
)
from .portfolio_engine_registry import (
    get_engine_class,
    get_engine_metric_function,
)


def compute_instrument(metric: str, instr_type: str, factors: dict) -> tuple[Any, dict]:  # previously compute()
    # Convenience method to simplify api.
    if None in (metric, instr_type, factors):
        raise ValueError("Missing input.")
    compute_cls = get_instrument_class(instr_type)
    function_name = get_metric_function(metric)
    obj = compute_cls(**factors)
    compute = getattr(obj, function_name)
    return compute()


def compute_portfolio(metric: str, instr_type: str, factors: dict) -> tuple[Any, dict]:
    # Convenience method to simplify api.
    if None in (metric, instr_type, factors):
        raise ValueError("Missing input.")
    compute_cls = get_engine_class(instr_type)
    function_name = get_engine_metric_function(metric)
    obj = compute_cls(**factors)
    compute = getattr(obj, function_name)
    return compute()


def compute(
    metric: str, instr_type: str, factors: dict
) -> tuple[Any, dict]:  # wrapper of instrument and portfolio compute
    # Convenience method to simplify api.
    if None in (metric, instr_type, factors):
        raise ValueError("Missing input.")
    if instr_type == "Portfolio":
        # Both arguments currently use the metric (e.g. "VaR").
        # May need sub-metric support for finer granularity in the future,
        # such as distinguishing position-level, attribution or stress tests.
        return compute_portfolio(metric, metric, factors)
    return compute_instrument(metric, instr_type, factors)
