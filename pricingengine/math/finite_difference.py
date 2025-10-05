"""Finite difference helper utilities."""

from __future__ import annotations


def central_difference(f_plus: float, f_minus: float, increment: float) -> float:
    """Compute the central difference derivative estimate.

    Parameters
    ----------
    f_plus:
        Function value at ``x + increment``.
    f_minus:
        Function value at ``x - increment``.
    increment:
        The increment size. Must be non-zero.

    Returns
    -------
    float
        The central difference ``(f_plus - f_minus) / (2 * increment)``.

    Raises
    ------
    ValueError
        If ``increment`` is zero.
    """

    if increment == 0:
        raise ValueError("'increment' cannot be zero")
    return (f_plus - f_minus) / (2 * increment)
