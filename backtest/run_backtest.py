"""Backtest runner: full strategy vs benchmarks, with optional walk-forward split.

Examples:
    python -m backtest.run_backtest --synthetic
    python -m backtest.run_backtest --symbol BTCUSDT          # uses cached real data
    python -m backtest.run_backtest --synthetic --split 0.7   # in/out-of-sample
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from backtest import benchmarks
from backtest import metrics as M
from common.config import load_params
from common.logging_util import setup_logging
from data import synthetic
from data.download import load_cached

log = logging.getLogger("backtest")


def _print_table(title: str, rows: dict[str, M.Metrics]) -> None:
    print(f"\n=== {title} ===")
    cols = list(next(iter(rows.values())).as_row().keys())
    name_w = max(len(n) for n in rows) + 2
    header = "Strategy".ljust(name_w) + "".join(c.rjust(15) for c in cols)
    print(header)
    print("-" * len(header))
    for name, m in rows.items():
        line = name.ljust(name_w) + "".join(str(v).rjust(15) for v in m.as_row().values())
        print(line)


def run(df: pd.DataFrame, params: dict, label: str = "Full sample") -> None:
    strat_m, _ = benchmarks.run_engine_backtest(df, params, signal_mode="full")
    naive_m, _ = benchmarks.run_engine_backtest(df, params, signal_mode="naive_breakout")
    bh_m, _ = benchmarks.buy_and_hold(df, params)
    _print_table(label, {
        "Squeeze (OF-confirmed)": strat_m,
        "Naive breakout": naive_m,
        "Buy & hold": bh_m,
    })


def main() -> None:
    setup_logging(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="use cached real data for this symbol")
    ap.add_argument("--interval", default=None)
    ap.add_argument("--synthetic", action="store_true", help="use generated synthetic data")
    ap.add_argument("--bars", type=int, default=3000, help="synthetic bars")
    ap.add_argument("--split", type=float, default=0.0, help="in-sample fraction for walk-forward (0=off)")
    ap.add_argument("--no-oi", action="store_true", help="drop OI from build-up (for long backtests; OI history is ~30d)")
    args = ap.parse_args()

    params = load_params()
    if args.no_oi:
        params["signal"]["use_oi"] = False
        log.warning("OI disabled in build-up (long-backtest mode)")
    symbol = args.symbol or params["symbol"]
    interval = args.interval or params["bar_interval"]

    if args.synthetic or args.symbol is None:
        log.warning("Using synthetic data (%d bars)", args.bars)
        df = synthetic.generate(n_bars=args.bars)
    else:
        df = load_cached(symbol, interval)
    print(f"Loaded {len(df)} bars for {symbol} {interval}")

    if args.split and 0 < args.split < 1:
        cut = int(len(df) * args.split)
        run(df.iloc[:cut].reset_index(drop=True), params, "In-sample")
        run(df.iloc[cut:].reset_index(drop=True), params, "Out-of-sample")
    else:
        run(df, params, "Full sample")


if __name__ == "__main__":
    main()