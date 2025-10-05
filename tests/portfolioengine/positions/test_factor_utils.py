import pytest
import QuantLib as ql

from PortfolioEngine import factor_utils


@pytest.fixture(autouse=True)
def reset_ql_state():
    ql.Settings.instance().evaluationDate = ql.Date()
    ql.IndexManager.instance().clearHistories()
    yield
    ql.IndexManager.instance().clearHistories()


def test_get_factors():
    result = factor_utils.get_factors("issuer")
    assert result == []
