"""Synthetic 5m data generator with engineered short-squeeze episodes.

Lets the backtest and tests run with no network/keys. Produces the same columns
as data.download.download_all so it is a drop-in replacement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate(n_bars: int = 2000, seed: int = 42, squeeze_every: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = 1_700_000_000_000  # arbitrary ms epoch
    step = 300_000

    price = 60_000.0
    oi = 50_000.0
    rows = []
    for i in range(n_bars):
        # background random walk
        ret = rng.normal(0, 0.0015)
        buy_share = rng.uniform(0.45, 0.55)
        funding = rng.normal(0.0001, 0.00005)

        phase = i % squeeze_every
        # build-up window: price flat, OI rising, selling absorbed, negative funding
        if 0 <= phase < 10:
            ret = rng.normal(-0.0003, 0.0008)   # mild down/flat
            oi *= 1.004                           # OI rising
            buy_share = rng.uniform(0.40, 0.50)   # net selling
            funding = rng.normal(-0.0003, 0.0001) # crowded shorts
        # squeeze: breakout + forced buying
        elif 10 <= phase < 14:
            ret = rng.normal(0.006, 0.002)        # sharp up
            oi *= 0.99                             # OI falling (shorts covering)
            buy_share = rng.uniform(0.62, 0.75)   # strong buy aggression
            funding = rng.normal(-0.0001, 0.0001)
        else:
            oi *= 1.0 + rng.normal(0, 0.001)

        open_p = price
        close_p = price * (1 + ret)
        high_p = max(open_p, close_p) * (1 + abs(rng.normal(0, 0.0008)))
        low_p = min(open_p, close_p) * (1 - abs(rng.normal(0, 0.0008)))
        volume = rng.uniform(50, 200) * (3 if 10 <= phase < 14 else 1)
        taker_buy = volume * buy_share

        ot = start + i * step
        rows.append({
            "open_time": ot, "close_time": ot + step - 1,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": volume, "num_trades": int(volume * 10),
            "taker_buy_volume": taker_buy, "open_interest": oi, "funding_rate": funding,
        })
        price = close_p

    return pd.DataFrame(rows)