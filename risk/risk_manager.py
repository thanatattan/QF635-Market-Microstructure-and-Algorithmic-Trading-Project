"""Portfolio-level risk: equity curve, drawdown kill-switch, pre-trade checks, VaR."""
from __future__ import annotations

from collections import deque

from risk import var as var_mod


class RiskManager:
    def __init__(self, params: dict) -> None:
        r = params["risk"]
        self._max_dd_pct = float(r["max_drawdown_pct"])
        self._max_notional = float(r["max_position_notional"])
        self._max_leverage = float(r["max_leverage"])
        self._var_conf = float(r["var_confidence"])
        self._var_horizon = int(r["var_horizon_bars"])

        self.equity_curve: list[float] = []
        self.peak_equity: float = 0.0
        self.current_drawdown: float = 0.0
        self.max_drawdown: float = 0.0
        self.kill_switch: bool = False
        self.kill_reason: str = ""
        self._returns: deque[float] = deque(maxlen=500)
        self._last_equity: float | None = None

    def on_equity_update(self, equity: float) -> None:
        if self._last_equity:
            self._returns.append((equity - self._last_equity) / self._last_equity)
        self._last_equity = equity
        self.equity_curve.append(equity)
        self.peak_equity = max(self.peak_equity, equity) if self.peak_equity else equity
        if self.peak_equity > 0:
            self.current_drawdown = (self.peak_equity - equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
            if self.current_drawdown >= self._max_dd_pct and not self.kill_switch:
                self.kill_switch = True
                self.kill_reason = f"max drawdown {self.current_drawdown:.1%} >= {self._max_dd_pct:.1%}"

    # relative tolerance absorbs float drift from sizing rounding / mark-price changes
    _TOL = 1e-6

    def pre_trade_check(self, intended_notional: float, equity: float,
                        current_position_notional: float) -> tuple[bool, str]:
        if self.kill_switch:
            return False, f"kill-switch active ({self.kill_reason})"
        gross = current_position_notional + intended_notional
        if intended_notional > self._max_notional * (1 + self._TOL):
            return False, f"order notional {intended_notional:.2f} > cap {self._max_notional:.2f}"
        if equity > 0:
            lev = gross / equity
            if lev > self._max_leverage * (1 + self._TOL):
                return False, f"gross leverage {lev:.4f}x > max {self._max_leverage:.4f}x"
        return True, "ok"

    def position_var(self, position_notional: float) -> float:
        # Parametric (Gaussian) VaR — understates crypto tails; pair with historical
        return var_mod.parametric_var(position_notional, list(self._returns),
                                      self._var_conf, self._var_horizon)

    def position_var_historical(self, position_notional: float) -> float:
        # Historical-simulation VaR — captures fat tails the Gaussian VaR misses
        return var_mod.historical_var(position_notional, list(self._returns),
                                      self._var_conf, self._var_horizon)

    def clear_manual_kill(self) -> None:
        # Allow the dashboard to switch a manual kill-switch back off (not a drawdown halt)
        if self.kill_switch and self.kill_reason.startswith("manual"):
            self.kill_switch = False
            self.kill_reason = ""

    def snapshot(self) -> dict:
        return {
            "equity": self._last_equity or 0.0,
            "peak_equity": self.peak_equity,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.max_drawdown,
            "kill_switch": self.kill_switch,
            "kill_reason": self.kill_reason,
        }