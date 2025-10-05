from portfolioengine import factor_utils


def test_get_factors():
    result = factor_utils.get_factors("issuer")
    assert result == []
