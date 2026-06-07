"""Benchmarks to compare the strategy against."""
from __future__ import annotations

import copy

import pandas as pd

from backtest import metrics as M
from engine.trading_engine import TradingEngine
from gateway.simulated_gateway import SimulatedGateway


def run_engine_backtest(df: pd.DataFrame, params: dict, signal_mode: str = "full") -> tuple[M.Metrics, list[float]]:
    """Run the full engine over historical data with a given signal mode."""
    p = copy.deepcopy(params)
    p["signal"]["mode"] = signal_mode
    gw = SimulatedGateway(p["symbol"], df, p)
    engine = TradingEngine(gw, p)   # no publisher in backtest
    engine.start()  # synchronous replay
    if engine.position_manager.position != 0:
        engine.order_manager.close(reason="backtest_end_flatten")
        engine.risk_manager.on_equity_update(engine.position_manager.equity)
    equity = engine.risk_manager.equity_curve
    return M.compute(equity, engine.position_manager.trades), equity


def buy_and_hold(df: pd.DataFrame, params: dict) -> tuple[M.Metrics, list[float]]:
    """Equity from holding 1 unit of notional = initial capital in BTC from bar 0."""
    cap = float(params["account"]["initial_capital"])
    closes = df["close"].tolist()
    if not closes:
        return M.Metrics(), []
    qty = cap / closes[0]
    equity = [qty * c for c in closes]
    # buy-and-hold has no discrete trades; synthesize one round trip for hit-rate context
    trades = [{"realized_pnl": equity[-1] - equity[0]}]
    return M.compute(equity, trades), equity