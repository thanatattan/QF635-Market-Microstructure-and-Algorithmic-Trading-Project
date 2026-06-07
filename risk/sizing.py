"""Volatility-targeted position sizing.

Risk a fixed fraction of equity per trade; the stop distance (a multiple of ATR)
determines quantity so that hitting the stop loses ~risk_per_trade_pct of equity.
Caps apply for max single-position notional and max leverage.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SizingResult:
    qty: float                  # base-asset quantity (>=0)
    stop_distance: float        # price distance to stop
    risk_amount: float          # USDT risked if stopped
    capped_by: str              # "" | "notional" | "leverage" | "no_atr"


def compute_size(equity: float, price: float, atr: float | None, params: dict,
                 stop_distance: float | None = None) -> SizingResult:
    """Size a trade so that hitting the stop loses ~risk_per_trade_pct of equity.

    `stop_distance` (price distance from entry to stop) may be passed explicitly so
    sizing matches the strategy's actual structural stop; if omitted it falls back to
    `stop_atr_mult * atr`.
    """
    r = params["risk"]
    risk_pct = float(r["risk_per_trade_pct"])
    stop_mult = float(r["stop_atr_mult"])
    max_notional = float(r["max_position_notional"])
    max_leverage = float(r["max_leverage"])

    if stop_distance is None:
        stop_distance = stop_mult * atr if atr else 0.0
    if stop_distance <= 0 or price <= 0:
        return SizingResult(qty=0.0, stop_distance=0.0, risk_amount=0.0, capped_by="no_stop")

    risk_amount = equity * risk_pct
    qty = risk_amount / stop_distance

    capped_by = ""
    # cap by single-position notional (the pre-trade check uses a small relative tolerance)
    if qty * price > max_notional:
        qty = max_notional / price
        capped_by = "notional"
    # cap by leverage (gross notional / equity)
    max_by_lev = (max_leverage * equity) / price
    if qty > max_by_lev:
        qty = max_by_lev
        capped_by = "leverage"

    return SizingResult(qty=max(qty, 0.0), stop_distance=stop_distance,
                        risk_amount=risk_amount, capped_by=capped_by)