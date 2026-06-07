"""TradingEngine: central router.

Owns the feature engine, signal engine, position/risk managers, order manager and
strategy. Wires gateway callbacks to them and publishes state to the dashboard.
The same engine drives live (Binance gateway) and backtest (simulated gateway).
"""
from __future__ import annotations

import logging
import threading

from common.interfaces import Kline, MarkPrice, OrderBook
from execution.order_manager import OrderManager
from features.engine import FeatureEngine
from features.signal import SqueezeSignalEngine
from gateway.base import Gateway
from risk.position_manager import PositionManager
from risk.risk_manager import RiskManager
from strategy.squeeze_strategy import SqueezeStrategy

log = logging.getLogger("engine")


class TradingEngine:
    def __init__(self, gateway: Gateway, params: dict, publisher=None) -> None:
        self._gw = gateway
        self._params = params
        self._publisher = publisher   # DashboardPublisher or None (backtest)
        self._lock = threading.Lock()

        self.feature_engine = FeatureEngine(params)
        self.signal_engine = SqueezeSignalEngine(params)
        self.position_manager = PositionManager(initial_capital=float(params["account"]["initial_capital"]))
        self.risk_manager = RiskManager(params)
        self.order_manager = OrderManager(gateway, self.position_manager, self.risk_manager, params)
        self.strategy = SqueezeStrategy(self.order_manager, self.position_manager, params)

        self._last_decision = None
        self._last_snapshot = None

        gateway.register_kline(self._on_kline)
        gateway.register_agg_trade(self.feature_engine.on_agg_trade)
        gateway.register_orderbook(self._on_orderbook)
        gateway.register_mark_price(self._on_mark_price)
        gateway.register_liquidation(self.feature_engine.on_liquidation)
        gateway.register_open_interest(self._on_open_interest)

    def start(self) -> None:
        log.info("TradingEngine starting (initial capital %.0f)", self.position_manager.initial_capital)
        # seed equity curve
        self.risk_manager.on_equity_update(self.position_manager.equity)
        self._gw.start()

    def stop(self) -> None:
        try:
            if self.position_manager.position != 0:
                self.order_manager.close(reason="shutdown_flatten")
        finally:
            self._gw.stop()
        log.info("TradingEngine stopped")

    # callbacks
    def _on_orderbook(self, ob: OrderBook) -> None:
        with self._lock:
            self.feature_engine.on_orderbook(ob)
            if ob.mid is not None:
                self.position_manager.update_mark(ob.mid)

    def _on_mark_price(self, m: MarkPrice) -> None:
        with self._lock:
            self.feature_engine.on_mark_price(m)
            self.position_manager.update_mark(m.mark_price)

    def _on_open_interest(self, oi) -> None:
        # routed through the engine lock so the OI-poll thread doesn't race the kline path
        with self._lock:
            self.feature_engine.on_open_interest(oi)

    def _on_kline(self, k: Kline) -> None:
        if not k.closed:
            return
        with self._lock:
            # honor the dashboard kill-switch in both directions (manual halts only)
            if self._publisher is not None:
                kill = self._publisher.get_kill()
                if kill and not self.risk_manager.kill_switch:
                    self.risk_manager.kill_switch = True
                    self.risk_manager.kill_reason = "manual (dashboard)"
                elif not kill:
                    self.risk_manager.clear_manual_kill()

            self.position_manager.update_mark(k.close)
            snap = self.feature_engine.on_kline(k)
            if snap is None:
                return
            decision = self.signal_engine.evaluate(snap)
            self.strategy.on_bar(snap, decision)
            self.risk_manager.on_equity_update(self.position_manager.equity)
            self._last_decision = decision
            self._last_snapshot = snap
            self._publish(snap, decision)

    # dashboard
    def _publish(self, snap, decision) -> None:
        if self._publisher is None:
            return
        notional = self.position_manager.position_notional
        var = self.risk_manager.position_var(notional)
        var_hist = self.risk_manager.position_var_historical(notional)
        self._publisher.publish({
            "timestamp": snap.timestamp,
            "price": snap.close,
            "breakout_level": snap.breakout_level,
            "signal_state": decision.state.value,
            "buildup_score": decision.buildup_score,
            "confirm_score": decision.confirm_score,
            "buildup_conditions": decision.buildup_conditions,
            "confirm_conditions": decision.confirm_conditions,
            "trend_ok": decision.trend_ok,
            "cvd": snap.cvd_cum,
            "open_interest": snap.open_interest,
            "funding_rate": snap.funding_rate,
            "taker_buy_ratio": snap.taker_buy_ratio,
            "short_liq_notional": snap.short_liq_notional,
            "atr": snap.atr,
            "position": self.position_manager.snapshot(),
            "risk": self.risk_manager.snapshot(),
            "var": var,
            "var_historical": var_hist,
            "strategy": self.strategy.state_snapshot(),
            "reason": decision.reason,
        })