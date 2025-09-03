from pricingengine.irs import InterestRateSwap
from pricingengine.termstructures.curve_nodes import CurveNodes


def test_api_surface() -> None:
    assert hasattr(CurveNodes, "bump")
    assert hasattr(CurveNodes, "yts_handle")
    assert hasattr(InterestRateSwap, "pv01")
    assert hasattr(InterestRateSwap, "dv01")
