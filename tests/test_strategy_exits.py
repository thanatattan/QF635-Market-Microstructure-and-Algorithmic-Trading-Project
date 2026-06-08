"""Exit-path tests — the module the review flagged as untested with the worst bug.

Verifies the ATR stop and take-profit actually fire now that the stop is anchored to
the structural breakout level (previously a soft 'below breakout' exit pre-empted them).
"""
import pandas as pd

from common.enums import SignalState
from execution.order_manager import OrderManager
from features.engine import FeatureSnapshot
from features.signal import SignalDecision
from risk.position_manager import PositionManager
from risk.risk_manager import RiskManager
from strategy.squeeze_strategy import SqueezeStrategy
from gateway.simulated_gateway import SimulatedGateway


def _snap(close, atr=100.0, breakout_level=99_900.0, **kw):
    base = dict(
        timestamp=0.0, close=close, prior_high_1h=breakout_level, prior_high_2h=breakout_level,
        breakout=True, breakout_level=breakout_level, cvd_cum=10.0, cvd_slope=1.0,
        bar_volume_delta=5.0, taker_buy_ratio=0.7, price_change_pct=0.0,
        open_interest=1000.0, oi_change_pct=0.02, funding_rate=-0.0002,
        atr=atr, realized_vol=0.01, spread_bps=2.0, short_liq_notional=100_000.0,
    )
    base.update(kw)
    return FeatureSnapshot(**base)


def _enter_decision():
    return SignalDecision(state=SignalState.CONFIRMED, enter=True, tradable=True,
                          buildup_score=3, confirm_score=3, breakout_level=99_900.0)


def _hold_decision():
    return SignalDecision(state=SignalState.IN_POSITION, enter=False, tradable=True,
                          buildup_score=0, confirm_score=0, breakout_level=99_900.0)


def _build(params):
    gw = SimulatedGateway("BTCUSDT", pd.DataFrame(), params)
    pm = PositionManager(initial_capital=100_000)
    rm = RiskManager(params); rm.on_equity_update(100_000)
    om = OrderManager(gw, pm, rm, params)
    strat = SqueezeStrategy(om, pm, params)
    return gw, pm, strat


def _bar(gw, pm, strat, snap, decision):
    gw._last_close = snap.close
    pm.update_mark(snap.close)
    strat.on_bar(snap, decision)


def test_entry_then_stop_loss_fires(params):
    gw, pm, strat = _build(params)
    _bar(gw, pm, strat, _snap(100_000.0), _enter_decision())
    assert strat.in_position and pm.position > 0
    stop = strat._trade.stop_price
    _bar(gw, pm, strat, _snap(stop - 50.0), _hold_decision())   # gap below the stop
    assert not strat.in_position
    assert pm.trades[-1]["reason"] == "stop_loss"


def test_entry_then_take_profit_fires(params):
    gw, pm, strat = _build(params)
    _bar(gw, pm, strat, _snap(100_000.0), _enter_decision())
    tp = strat._trade.take_profit_price
    _bar(gw, pm, strat, _snap(tp + 50.0), _hold_decision())
    assert not strat.in_position
    assert pm.trades[-1]["reason"] == "take_profit"


def test_time_stop_fires(params):
    gw, pm, strat = _build(params)
    _bar(gw, pm, strat, _snap(100_000.0), _enter_decision())
    n = params["risk"]["time_stop_bars"]
    # hold flat (between stop and TP) until the time stop triggers
    for _ in range(n):
        _bar(gw, pm, strat, _snap(100_010.0), _hold_decision())
    assert not strat.in_position
    assert pm.trades[-1]["reason"] == "time_stop"


def test_stop_is_below_entry_and_reachable(params):
    """Regression for the dead-stop bug: stop must sit below entry, not above it."""
    gw, pm, strat = _build(params)
    _bar(gw, pm, strat, _snap(100_000.0), _enter_decision())
    t = strat._trade
    assert t.stop_price < t.entry_price < t.take_profit_price


def test_rejected_close_keeps_trade(params):
    """If the exit order is rejected, _trade must NOT be cleared (no orphaned position)."""
    from common.enums import OrderStatus, Side
    from common.events import OrderEvent
    gw, pm, strat = _build(params)
    _bar(gw, pm, strat, _snap(100_000.0), _enter_decision())
    assert strat.in_position
    # force the close to report a rejection
    strat._om.close = lambda reason="exit": OrderEvent(
        timestamp=0, symbol="BTCUSDT", side=Side.SELL, status=OrderStatus.REJECTED,
        price=0.0, quantity=0.0, reason="simulated rejection")
    stop = strat._trade.stop_price
    _bar(gw, pm, strat, _snap(stop - 50.0), _hold_decision())   # would trigger stop
    assert strat.in_position   # trade retained for retry, not orphaned