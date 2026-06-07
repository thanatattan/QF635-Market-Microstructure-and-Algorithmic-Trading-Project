import copy

import pytest

from dashboard.publisher import DashboardPublisher
from dashboard.sink import FileSink, make_sink


def test_filesink_roundtrip(tmp_path):
    sink = FileSink(tmp_path)
    sink.publish({"price": 100.0, "history": {"ts": [1, 2], "price": [99, 100]}})
    latest = sink.read_latest()
    assert latest["price"] == 100.0
    assert latest["history"]["price"] == [99, 100]
    assert "published_at" in latest


def test_filesink_kill_switch(tmp_path):
    sink = FileSink(tmp_path)
    assert sink.get_kill() is False        # no file yet
    sink.set_kill(True)
    assert sink.get_kill() is True
    sink.set_kill(False)
    assert sink.get_kill() is False


def test_filesink_empty_read(tmp_path):
    assert FileSink(tmp_path).read_latest() == {}


def test_make_sink_file(tmp_path, params):
    p = copy.deepcopy(params)
    p["dashboard"]["sink"] = "file"
    p["dashboard"]["state_dir"] = str(tmp_path)
    sink = make_sink(p)
    assert isinstance(sink, FileSink)


def test_make_sink_redis_requires_url(params, monkeypatch):
    p = copy.deepcopy(params)
    p["dashboard"]["sink"] = "redis"
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RuntimeError):
        make_sink(p)   # must fail clearly, and without importing redis at module load


def test_engine_publishes_through_filesink(tmp_path, params):
    """End-to-end (offline): engine -> publisher -> FileSink, decoupled reader can read it."""
    from data import synthetic
    from gateway.simulated_gateway import SimulatedGateway
    from engine.trading_engine import TradingEngine

    sink = FileSink(tmp_path)
    pub = DashboardPublisher(sink)
    eng = TradingEngine(SimulatedGateway("BTCUSDT", synthetic.generate(300), params), params, publisher=pub)
    eng.start()
    latest = sink.read_latest()
    assert latest.get("history", {}).get("ts")          # history populated
    assert "equity" in latest.get("position", {})       # latest snapshot populated
    assert pub.get_kill() is False


def test_publisher_builds_history(tmp_path):
    sink = FileSink(tmp_path)
    pub = DashboardPublisher(sink)
    for i in range(3):
        pub.publish({
            "timestamp": i, "price": 100 + i, "breakout_level": 99,
            "signal_state": "IDLE", "cvd": i, "open_interest": 1000,
            "position": {"equity": 100000 + i}, "risk": {"current_drawdown": 0.0},
        })
    latest = sink.read_latest()
    assert latest["history"]["price"] == [100, 101, 102]
    assert latest["history"]["equity"] == [100000, 100001, 100002]
    assert pub.get_kill() is False