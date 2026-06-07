"""Offline demo: replay data through the engine into the dashboard sink.

Lets you SEE the dashboard with no live code and no API keys. Run this in one
terminal and `python -m scripts.run_dashboard` in another, then open the dashboard.

    python -m scripts.run_demo --synthetic --delay 0.3     # animated, ~live-looking
    python -m scripts.run_demo --synthetic                 # instant (fills the file, static view)
    python -m scripts.run_demo --symbol BTCUSDT --delay 0.2  # replay cached real data
    python -m scripts.run_demo --synthetic --delay 0.3 --loop  # keep looping for a long demo
"""
from __future__ import annotations

import argparse
import logging

from common.config import load_params
from common.logging_util import setup_logging
from dashboard.publisher import DashboardPublisher
from dashboard.sink import make_sink
from data import synthetic
from data.download import load_cached
from engine.trading_engine import TradingEngine
from gateway.simulated_gateway import SimulatedGateway

log = logging.getLogger("run_demo")


def main() -> None:
    setup_logging(logging.INFO)
    params = load_params()
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="use cached real data for this symbol")
    ap.add_argument("--synthetic", action="store_true", help="use generated synthetic data")
    ap.add_argument("--bars", type=int, default=2000, help="synthetic bars")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between bars (0 = instant)")
    ap.add_argument("--loop", action="store_true", help="restart replay when it finishes")
    args = ap.parse_args()

    symbol = args.symbol or params["symbol"]
    if args.synthetic or args.symbol is None:
        df = synthetic.generate(n_bars=args.bars)
        log.info("Replaying %d synthetic bars (delay=%.2fs)", len(df), args.delay)
    else:
        df = load_cached(symbol, params["bar_interval"])
        log.info("Replaying %d cached %s bars (delay=%.2fs)", len(df), symbol, args.delay)

    sink = make_sink(params)
    log.info("Publishing to %s sink. View with:  python -m scripts.run_dashboard", params["dashboard"].get("sink", "file"))

    while True:
        publisher = DashboardPublisher(sink)
        gateway = SimulatedGateway(symbol, df, params, bar_delay=args.delay)
        engine = TradingEngine(gateway, params, publisher=publisher)
        engine.start()   # replays synchronously, publishing each bar
        if not args.loop:
            break
        log.info("Replay finished — looping")

if __name__ == "__main__":
    main()