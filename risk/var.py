"""Value-at-Risk estimates for the current position.

Two methods are provided; the dashboard shows parametric VaR by default.
VaR is expressed as a positive number = potential loss in USDT over the horizon
at the given confidence.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from scipy.stats import norm


def parametric_var(position_notional: float, returns: Sequence[float],
                   confidence: float = 0.99, horizon: int = 1) -> float:
    # Gaussian VaR: z * sigma * sqrt(horizon) * notional
    if position_notional <= 0 or len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    sigma = math.sqrt(var)
    z = norm.ppf(confidence)
    return z * sigma * math.sqrt(horizon) * position_notional

def historical_var(position_notional: float, returns: Sequence[float],
                   confidence: float = 0.99, horizon: int = 1) -> float:
    # Historical-simulation VaR from the empirical return distribution
    if position_notional <= 0 or len(returns) < 2:
        return 0.0
    scaled = sorted(r * math.sqrt(horizon) for r in returns)
    idx = int((1 - confidence) * len(scaled))
    idx = min(max(idx, 0), len(scaled) - 1)
    worst = scaled[idx]
    return max(-worst, 0.0) * position_notional