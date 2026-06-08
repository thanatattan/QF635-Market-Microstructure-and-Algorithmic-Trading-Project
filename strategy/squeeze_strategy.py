"""Short-squeeze momentum strategy (long-only).

Entry: when the composite signal confirms a squeeze, size by volatility and go long.
Exit: stop / take-profit / time-stop, plus squeeze-failure exits (price falls back
below the breakout level, buy aggression fades, CVD turns down).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from common.enums import Side
from execution.order_manager import OrderManager
from features.engine import FeatureSnapshot
from features.signal import SignalDecision
from risk import sizing
from risk.position_manager import PositionManager

log = logging.getLogger("strategy")


@dataclass
class TradeState:
    entry_price: float
    stop_price: float
    take_profit_price: float
    breakout_level: float
    bars_in_trade: int = 0

class SqueezeStrategy:
    def __init__(self, order_manager: OrderManager, position_manager: PositionManager, params: dict) -> None:
        self._om = order_manager
        self._pm = position_manager
        self._params = params
        self._time_stop = int(params["risk"]["time_stop_bars"])
        self._tp_r = float(params["risk"]["take_profit_r"])
        self._stop_atr_mult = float(params["risk"]["stop_atr_mult"])
        self._trade: TradeState | None = None
        self.last_action: str = ""

    def _stop_from_breakout(self, breakout_level: float, atr: float) -> float:
        """Structural stop: a buffer below the reclaimed breakout level.

        Anchoring the stop to the level we broke (rather than a free-floating
        ATR offset from entry) makes the stop the single, real risk control —
        a fall back below the breakout *is* the invalidation, so there is no
        separate soft exit that pre-empts it.
        """
        return breakout_level - self._stop_atr_mult * atr

    @property
    def in_position(self) -> bool:
        return self._pm.position != 0 and self._trade is not None

    def on_bar(self, snap: FeatureSnapshot, decision: SignalDecision) -> None:
        # Called once per closed bar with the latest features + signal decision
        if self.in_position:
            self._manage_exit(snap)
        else:
            self._maybe_enter(snap, decision)

    def _maybe_enter(self, snap: FeatureSnapshot, decision: SignalDecision) -> None:
        if not decision.enter:
            return
        if not snap.atr or snap.atr <= 0:
            self.last_action = "entry skipped (no ATR)"
            return
        breakout_level = snap.breakout_level or snap.close
        prelim_stop = self._stop_from_breakout(breakout_level, snap.atr)
        stop_distance = snap.close - prelim_stop
        if stop_distance <= 0:
            self.last_action = "entry skipped (close already below structural stop)"
            return
        size = sizing.compute_size(self._pm.equity, snap.close, snap.atr,
                                   self._params, stop_distance=stop_distance)
        if size.qty <= 0:
            self.last_action = f"entry skipped (sizing: {size.capped_by or 'zero qty'})"
            return
        ev = self._om.enter(Side.BUY, size.qty, snap.close, reason="squeeze_entry")
        if ev is None or not ev.is_fill:
            self.last_action = f"entry rejected ({self._om.last_rejection})"
            return
        entry = ev.price
        stop_price = self._stop_from_breakout(breakout_level, snap.atr)
        self._trade = TradeState(
            entry_price=entry,
            stop_price=stop_price,
            take_profit_price=entry + self._tp_r * (entry - stop_price),
            breakout_level=breakout_level,
        )
        self.last_action = f"ENTER long {ev.quantity:.4f} @ {entry:.2f} (stop {stop_price:.2f})"
        log.info(self.last_action)

    def _manage_exit(self, snap: FeatureSnapshot) -> None:
        t = self._trade
        assert t is not None
        t.bars_in_trade += 1
        price = snap.close
        reason = None

        # stop_price sits below the broken level, so "fell back below breakout" and
        # "hit the stop" are the same event — the ATR-based stop genuinely governs risk.
        if price <= t.stop_price:
            reason = "stop_loss"
        elif price >= t.take_profit_price:
            reason = "take_profit"
        elif t.bars_in_trade >= self._time_stop:
            reason = "time_stop"
        elif snap.taker_buy_ratio < 0.5 and (snap.cvd_slope or 0) < 0:
            # taker_buy_ratio < 0.5 already implies bar_volume_delta < 0 (same thing),
            # so the rule is: this bar net-sold AND cumulative CVD is rolling over.
            reason = "momentum_fade"

        if reason:
            ev = self._om.close(reason=reason)
            if ev is not None and ev.is_fill:
                self._trade = None
                self.last_action = f"EXIT @ {ev.price:.2f} ({reason})"
                log.info(self.last_action)
            else:
                # close rejected/unfilled — keep _trade so we retry next bar (no orphaned position)
                self.last_action = f"EXIT {reason} NOT filled ({self._om.last_rejection}); will retry"
                log.warning(self.last_action)

    def state_snapshot(self) -> dict:
        if self._trade is None:
            return {"in_position": False, "last_action": self.last_action}
        t = self._trade
        return {
            "in_position": True,
            "entry_price": t.entry_price,
            "stop_price": t.stop_price,
            "take_profit_price": t.take_profit_price,
            "breakout_level": t.breakout_level,
            "bars_in_trade": t.bars_in_trade,
            "last_action": self.last_action,
        }