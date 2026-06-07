"""Rolling tracker of recent forced liquidations (live stream only).

Short liquidations (forced buying) are the most direct evidence of a squeeze.
This keeps a time-windowed sum of short-liquidation notional.
"""
from __future__ import annotations

from collections import deque

from common.interfaces import Liquidation


class LiquidationTracker:
    def __init__(self, lookback_seconds: int) -> None:
        self._lookback_ms = lookback_seconds * 1000
        self._events: deque[Liquidation] = deque()

    def on_liquidation(self, liq: Liquidation) -> None:
        self._events.append(liq)
        self._evict(liq.timestamp)

    def _evict(self, now_ms: float) -> None:
        while self._events and now_ms - self._events[0].timestamp > self._lookback_ms:
            self._events.popleft()

    def short_liq_notional(self, now_ms: float) -> float:
        # Total notional of SHORT liquidations (forced buying) in the window
        self._evict(now_ms)
        return sum(e.notional for e in self._events if e.is_short_liquidation)

    def long_liq_notional(self, now_ms: float) -> float:
        self._evict(now_ms)
        return sum(e.notional for e in self._events if not e.is_short_liquidation)