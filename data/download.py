"""Download historical Binance USD-M futures data for backtesting.

Uses public mainnet endpoints (no key needed; real history — testnet has little).
Produces one merged 5m DataFrame: klines + open-interest history + funding rate.

NOTE: open-interest history is only available for ~the last 30 days, and
liquidation history is NOT available via REST (live stream only) — so the
backtest omits the liquidation confirmation signal (documented limitation).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from common.config import ROOT

log = logging.getLogger("data.download")
CACHE = ROOT / "data" / "cache"

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def _client():
    from binance import Client  # lazy import: only needed for live downloads
    return Client()  # public mainnet, no auth needed for market data


def download_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    client = _client()
    step = INTERVAL_MS[interval]
    rows: list[list] = []
    cur = start_ms
    while cur < end_ms:
        batch = client.futures_klines(symbol=symbol, interval=interval,
                                      startTime=cur, endTime=end_ms, limit=1500)
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + step
        time.sleep(0.2)
        if len(batch) < 1500:
            break
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_vol", "num_trades", "taker_buy_base", "taker_buy_quote", "ignore"])
    df = df.astype({"open": float, "high": float, "low": float, "close": float,
                    "volume": float, "num_trades": int, "taker_buy_base": float})
    df = df.rename(columns={"taker_buy_base": "taker_buy_volume"})
    return df[["open_time", "close_time", "open", "high", "low", "close",
               "volume", "num_trades", "taker_buy_volume"]].drop_duplicates("open_time")


def download_open_interest(symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    client = _client()
    try:
        data = client.futures_open_interest_hist(symbol=symbol, period=period,
                                                 limit=500, startTime=start_ms, endTime=end_ms)
    except Exception as exc:  # noqa: BLE001
        log.warning("OI history unavailable: %s", exc)
        return pd.DataFrame(columns=["close_time", "open_interest"])
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=["close_time", "open_interest"])
    df["close_time"] = df["timestamp"].astype("int64")
    df["open_interest"] = df["sumOpenInterest"].astype(float)
    return df[["close_time", "open_interest"]]


def download_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    client = _client()
    rows: list[dict] = []
    cur = start_ms
    while cur < end_ms:                      # paginate (1000/call ≈ 333 days) for long ranges
        batch = client.futures_funding_rate(symbol=symbol, startTime=cur, endTime=end_ms, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        cur = int(batch[-1]["fundingTime"]) + 1
        time.sleep(0.2)
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["close_time", "funding_rate"])
    df = df.drop_duplicates("fundingTime")
    df["close_time"] = df["fundingTime"].astype("int64")
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df[["close_time", "funding_rate"]]


def download_all(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Download and merge klines + OI + funding for the last `days` days."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    log.info("Downloading %s %s for last %d days…", symbol, interval, days)

    klines = download_klines(symbol, interval, start_ms, end_ms)
    oi = download_open_interest(symbol, interval, start_ms, end_ms)
    funding = download_funding(symbol, start_ms, end_ms)

    df = klines.copy()
    if not oi.empty:
        df = pd.merge_asof(df.sort_values("close_time"), oi.sort_values("close_time"),
                           on="close_time", direction="nearest", tolerance=INTERVAL_MS[interval])
    if not funding.empty:
        df = pd.merge_asof(df.sort_values("close_time"), funding.sort_values("close_time"),
                           on="close_time", direction="backward")
        df["funding_rate"] = df["funding_rate"].ffill().fillna(0.0)

    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{symbol}_{interval}.csv"
    df.to_csv(out, index=False)
    log.info("Saved %d rows to %s", len(df), out)
    return df


def load_cached(symbol: str, interval: str) -> pd.DataFrame:
    path = CACHE / f"{symbol}_{interval}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No cached data at {path}. Run scripts/download_all.py first.")
    return pd.read_csv(path)