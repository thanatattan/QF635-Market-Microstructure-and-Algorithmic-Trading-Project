"""Filter ablation study: measure each filter's marginal contribution.

Runs the strategy with each filter turned off (one at a time) and compares against the
full stack and a naive-breakout floor, on the full sample and the walk-forward split.
Interpret by robustness across in-sample AND out-of-sample, not best-on-sample.

    python -m scripts.ablation --symbol BTCUSDT --no-oi --split 0.7
    python -m scripts.ablation --synthetic
"""
from __future__ import annotations

import argparse
import copy
import logging

import pandas as pd

from backtest import benchmarks
from backtest import metrics as M
from common.config import load_params
from common.logging_util import setup_logging
from data import synthetic
from data.download import load_cached

# (label, param overrides by section, signal_mode)
VARIANTS = [
    ("Baseline (full stack)", {}, "full"),
    ("- build-up gate",   {"signal": {"min_buildup_score": 0}}, "full"),
    ("- confirmation",    {"signal": {"min_confirm_score": 0}}, "full"),
    ("- trend filter",    {"signal": {"use_trend_filter": False}}, "full"),
    ("- momentum-fade",   {"risk": {"use_momentum_fade": False}}, "full"),
    ("Naive (breakout only)", {}, "naive_breakout"),
]


def _apply(base: dict, overrides: dict) -> dict:
    p = copy.deepcopy(base)
    for section, kv in overrides.items():
        p[section].update(kv)
    return p


def _table(title: str, df: pd.DataFrame, base: dict) -> None:
    print(f"\n=== {title} ({len(df)} bars) ===")
    hdr = f'{"Variant":<24}{"Return":>9}{"Sharpe":>8}{"MaxDD":>8}{"Trades":>8}{"Hit":>6}{"PF":>7}'
    print(hdr); print("-" * len(hdr))
    for label, ov, mode in VARIANTS:
        m, _ = benchmarks.run_engine_backtest(df, _apply(base, ov), mode)
        print(f'{label:<24}{m.total_return:>8.2%}{m.sharpe:>8.2f}{m.max_drawdown:>7.2%}'
              f'{m.num_trades:>8}{m.hit_rate:>6.0%}{m.profit_factor:>7.2f}')


def main() -> None:
    setup_logging(logging.ERROR)   # quiet risk warnings during the sweep
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--bars", type=int, default=3000)
    ap.add_argument("--split", type=float, default=0.0)
    ap.add_argument("--no-oi", action="store_true")
    args = ap.parse_args()

    base = load_params()
    if args.no_oi:
        base["signal"]["use_oi"] = False
    symbol = args.symbol or base["symbol"]

    if args.synthetic or args.symbol is None:
        df = synthetic.generate(n_bars=args.bars)
    else:
        df = load_cached(symbol, base["bar_interval"])
    print(f"Ablation on {len(df)} bars ({symbol})  | OI={'on' if base['signal'].get('use_oi', True) else 'off'}")

    if args.split and 0 < args.split < 1:
        cut = int(len(df) * args.split)
        _table("In-sample", df.iloc[:cut].reset_index(drop=True), base)
        _table("Out-of-sample", df.iloc[cut:].reset_index(drop=True), base)
    else:
        _table("Full sample", df, base)


if __name__ == "__main__":
    main()
