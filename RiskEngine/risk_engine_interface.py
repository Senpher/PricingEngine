"""Minimal risk engine stub used by the portfolio engine registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InitializeRiskEngine:
    """Placeholder implementation for the portfolio risk engine.

    The original project integrates with a proprietary risk engine.  For the
    open-source version we keep the public interface but raise an explicit
    error when the portfolio specific metrics are requested.  This keeps the
    import structure intact while signalling clearly that the functionality is
    not yet implemented.
    """

    def get_portfolio_var(self, *args, **kwargs):  # noqa: D401 - keep signature flexible
        """Placeholder for Value-at-Risk calculation.

        The production system would return a Value-at-Risk figure together with
        diagnostics.  The current implementation raises ``NotImplementedError``
        to make it obvious to callers that the behaviour is not available in
        this repository.
        """

        raise NotImplementedError("Portfolio VaR computation is not implemented in the open-source portfolio engine.")
