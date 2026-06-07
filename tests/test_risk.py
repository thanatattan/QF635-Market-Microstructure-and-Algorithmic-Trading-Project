from risk import sizing
from risk.risk_manager import RiskManager


def test_sizing_respects_notional_cap(params):
    # tiny ATR -> huge raw qty -> must be capped by max_position_notional
    res = sizing.compute_size(equity=100_000, price=60_000, atr=1.0, params=params)
    assert res.qty * 60_000 <= params["risk"]["max_position_notional"] + 1e-6
    assert res.capped_by in ("notional", "leverage")


def test_sizing_no_atr(params):
    res = sizing.compute_size(equity=100_000, price=60_000, atr=None, params=params)
    assert res.qty == 0.0 and res.capped_by == "no_stop"


def test_sizing_explicit_stop_distance(params):
    # risk 0.5% of 100k = 500; stop distance 250 -> 2 BTC before caps
    res = sizing.compute_size(equity=100_000, price=100.0, atr=10.0,
                              params=params, stop_distance=250.0)
    assert res.stop_distance == 250.0
    assert abs(res.qty - 2.0) < 1e-9  # 100*2 = 200 notional, well under caps


def test_pre_trade_check_passes_at_exact_cap(params):
    from risk.risk_manager import RiskManager
    rm = RiskManager(params)
    rm.on_equity_update(100_000)
    cap = params["risk"]["max_position_notional"]
    ok, _ = rm.pre_trade_check(cap, 100_000, 0)   # exactly at cap must pass (tolerance)
    assert ok is True


def test_kill_switch_triggers(params):
    rm = RiskManager(params)
    rm.on_equity_update(100_000)
    rm.on_equity_update(80_000)   # 20% drawdown > 10% threshold
    assert rm.kill_switch is True
    ok, _ = rm.pre_trade_check(1_000, 80_000, 0)
    assert ok is False


def test_leverage_check(params):
    rm = RiskManager(params)
    rm.on_equity_update(100_000)
    max_lev = params["risk"]["max_leverage"]
    # request notional above leverage cap
    ok, _ = rm.pre_trade_check(max_lev * 100_000 + 1_000, 100_000, 0)
    assert ok is False