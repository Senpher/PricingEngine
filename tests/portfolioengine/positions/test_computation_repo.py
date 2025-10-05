from rvs_engine_interface import computation


def test_integrate_and_compute_repo():
    factors = {  # from position SWAP202633
        "pos_name": "RE00004647",  # Traderef: to keep track of which example
        "ccy": "DKK",
        "day_count": "Actual360",
        "repo_rate": 1.75,
        "value_date": "2025-07-15",
        "issue_date": "2025-07-11",
        "maturity": "2025-07-25",
        "initial_cash_amount": 999997171.2,
        "underlying_nominal": 995000000,
        "underlying_dirty_price": 100.5795652,
        "hair_cut": 0,
    }

    mtm, used_factors, warning_message = computation.compute(
        "MTM", instr_type="Repo", factors=factors
    )
    assert mtm == 18674886.900000095
    assert used_factors == {
        "initial_cash_amount": 999997171.2,
        "accrued_interest": 19444389.44,
        "cash_value": 1019441560.6400001,
        "dirty_price": 100.5795652,
        "bond_nominal": 995000000,
        "hair_cut": 0,
        "collateral_value": 1000766673.74,
    }
    assert warning_message is None
