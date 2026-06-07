"""Download historical data for backtesting.

    python -m scripts.download_all --days 30
"""
from __future__ import annotations

import argparse
import logging

from common.config import load_params
from common.logging_util import setup_logging
from data.download import download_all


def main() -> None:
    setup_logging(logging.INFO)
    params = load_params()
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=params["symbol"])
    ap.add_argument("--interval", default=params["bar_interval"])
    ap.add_argument("--days", type=int, default=30, help="OI history limited to ~30 days")
    args = ap.parse_args()
    download_all(args.symbol, args.interval, args.days)

if __name__ == "__main__":
    main()