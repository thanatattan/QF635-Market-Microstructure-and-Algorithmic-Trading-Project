"""Pure indicator functions (no state) — easy to unit test.

All take plain sequences of floats and return floats / bools. Used by the
FeatureEngine to build a per-bar snapshot.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def rolling_high(highs: Sequence[float], lookback: int) -> float | None:
    """Highest high over the last `lookback` *completed prior* bars.

    Excludes the current (last) bar so a breakout compares the current close to
    the prior range, avoiding a bar breaking out against itself.
    """
    if len(highs) < lookback + 1:
        return None
    window = highs[-lookback - 1:-1]
    return max(window)


def is_breakout(close: float, prior_high: float | None) -> bool:
    return prior_high is not None and close > prior_high


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int) -> float | None:
    #Average True Range over `window` bars
    if len(closes) < window + 1:
        return None
    trs = [true_range(highs[i], lows[i], closes[i - 1]) for i in range(len(closes) - window, len(closes))]
    return sum(trs) / len(trs)


def log_returns(closes: Sequence[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            out.append(math.log(closes[i] / closes[i - 1]))
    return out


def realized_vol(closes: Sequence[float], window: int) -> float | None:
    # Standard deviation of log returns over the last `window` bars
    rets = log_returns(closes)
    if len(rets) < window:
        return None
    w = rets[-window:]
    mean = sum(w) / len(w)
    var = sum((r - mean) ** 2 for r in w) / (len(w) - 1) if len(w) > 1 else 0.0
    return math.sqrt(var)


def pct_change(series: Sequence[float], window: int) -> float | None:
    """Fractional change of `series` over `window` bars: (last - first) / first."""
    if len(series) < window + 1 or series[-window - 1] == 0:
        return None
    first = series[-window - 1]
    return (series[-1] - first) / abs(first)


def sma(series: Sequence[float], window: int) -> float | None:
    # Simple moving average of the last `window` values
    if len(series) < window:
        return None
    w = series[-window:]
    return sum(w) / len(w)


def slope(series: Sequence[float], window: int) -> float | None:
    # Mean per-step change over the last `window` points (simple slope)
    if len(series) < window + 1:
        return None
    w = series[-window - 1:]
    return (w[-1] - w[0]) / window