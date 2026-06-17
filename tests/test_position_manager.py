from common.enums import OrderStatus, Side
from common.events import OrderEvent
from risk.position_manager import PositionManager


def _fill(side, price, qty, fee=0.0):
    return OrderEvent(timestamp=0, symbol="BTCUSDT", side=side, status=OrderStatus.FILLED,
                      price=price, quantity=qty, fee=fee)


def test_long_roundtrip_profit():
    pm = PositionManager(initial_capital=100_000)
    pm.on_fill(_fill(Side.BUY, 100.0, 2.0))
    assert pm.position == 2.0 and pm.avg_price == 100.0
    pm.update_mark(110.0)
    assert pm.unrealized_pnl == 20.0
    realized = pm.on_fill(_fill(Side.SELL, 110.0, 2.0))
    assert realized == 20.0
    assert pm.position == 0.0
    assert pm.realized_pnl == 20.0
    assert pm.equity == 100_020.0


def test_short_roundtrip_profit():
    pm = PositionManager(initial_capital=100_000)
    pm.on_fill(_fill(Side.SELL, 100.0, 1.0))
    assert pm.position == -1.0
    realized = pm.on_fill(_fill(Side.BUY, 90.0, 1.0))
    assert realized == 10.0


def test_average_price_on_add():
    pm = PositionManager(initial_capital=100_000)
    pm.on_fill(_fill(Side.BUY, 100.0, 1.0))
    pm.on_fill(_fill(Side.BUY, 200.0, 1.0))
    assert pm.avg_price == 150.0
    assert pm.position == 2.0


def test_round_qty_no_float_dust():
    from gateway.base import SymbolFilters
    f = SymbolFilters(tick_size=0.1, step_size=0.001, min_notional=5.0)
    assert f.round_qty(0.167) == 0.167      # must not floor to 0.166 via float error
    assert f.round_qty(0.123) == 0.123


def test_round_trip_recorded():
    pm = PositionManager(initial_capital=100_000)
    pm.on_fill(_fill(Side.BUY, 100.0, 2.0))     # open
    assert pm.round_trips == []                   # not closed yet
    pm.on_fill(_fill(Side.SELL, 110.0, 2.0))    # close
    assert len(pm.round_trips) == 1
    rt = pm.round_trips[0]
    assert rt["realized_pnl"] == 20.0
    assert rt["entry_price"] == 100.0 and rt["exit_price"] == 110.0


def test_fees_reduce_equity():
    pm = PositionManager(initial_capital=100_000)
    pm.on_fill(_fill(Side.BUY, 100.0, 1.0, fee=5.0))
    pm.update_mark(100.0)
    assert pm.equity == 100_000 - 5.0