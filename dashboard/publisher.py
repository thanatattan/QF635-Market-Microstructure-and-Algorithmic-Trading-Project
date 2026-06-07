"""Producer-side dashboard publisher.

Holds the rolling history and writes a full snapshot (latest fields + history arrays)
through a StateSink. The engine calls `publish(state)` each bar and `get_kill()` to read
the dashboard's kill-switch. Replaces the old in-process DashboardStore.
"""
from __future__ import annotations

from collections import deque

from dashboard.sink import StateSink


class DashboardPublisher:
    def __init__(self, sink: StateSink, maxlen: int = 2000) -> None:
        self._sink = sink
        self._ts: deque = deque(maxlen=maxlen)
        self._price: deque = deque(maxlen=maxlen)
        self._breakout: deque = deque(maxlen=maxlen)
        self._equity: deque = deque(maxlen=maxlen)
        self._drawdown: deque = deque(maxlen=maxlen)
        self._cvd: deque = deque(maxlen=maxlen)
        self._oi: deque = deque(maxlen=maxlen)
        self._state: deque = deque(maxlen=maxlen)

    def publish(self, state: dict) -> None:
        self._ts.append(state.get("timestamp"))
        self._price.append(state.get("price"))
        self._breakout.append(state.get("breakout_level"))
        self._equity.append(state.get("position", {}).get("equity"))
        self._drawdown.append(state.get("risk", {}).get("current_drawdown"))
        self._cvd.append(state.get("cvd"))
        self._oi.append(state.get("open_interest"))
        self._state.append(state.get("signal_state"))

        payload = dict(state)
        payload["history"] = {
            "ts": list(self._ts), "price": list(self._price), "breakout": list(self._breakout),
            "equity": list(self._equity), "drawdown": list(self._drawdown),
            "cvd": list(self._cvd), "oi": list(self._oi), "state": list(self._state),
        }
        self._sink.publish(payload)

    def get_kill(self) -> bool:
        return self._sink.get_kill()