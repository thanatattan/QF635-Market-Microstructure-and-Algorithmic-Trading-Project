"""Run the live paper-trading engine on Binance Futures testnet.

    python -m scripts.run_live

The engine streams data in background threads and publishes state through the
configured sink (file or redis). Run the dashboard SEPARATELY:

    python -m scripts.run_dashboard

Requires a .env with testnet API keys (see .env.example).
"""
from __future__ import annotations

import logging
import threading

from common.config import load_config
from common.logging_util import setup_logging
from dashboard.publisher import DashboardPublisher
from dashboard.sink import make_sink
from engine.trading_engine import TradingEngine
from gateway.binance_gateway import BinanceFuturesGateway

log = logging.getLogger("run_live")


def main() -> None:
    setup_logging(logging.INFO)
    params = load_config()
    cred = params["_credentials"]

    sink = make_sink(params)
    publisher = DashboardPublisher(sink)
    gateway = BinanceFuturesGateway(params["symbol"], cred, params)

    # Live runs on the real testnet balance (the demo account is locked at ~5k);
    # the backtest keeps the 100k brief from params.yaml.
    if params["account"].get("sync_live_balance", False):
        bal = gateway.fetch_usdt_balance()
        if bal:
            log.info("Syncing initial capital to live testnet balance: %.2f USDT", bal)
            params["account"]["initial_capital"] = bal
        else:
            log.warning("Live balance unavailable; using configured %.0f USDT",
                        params["account"]["initial_capital"])

    engine = TradingEngine(gateway, params, publisher=publisher)

    try:
        engine.start()
        log.info("Engine running. Start the dashboard with:  python -m scripts.run_dashboard")
        threading.Event().wait()   # keep main thread alive; ws runs in background threads
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
    finally:
        engine.stop()

if __name__ == "__main__":
    main()