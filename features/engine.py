"""FeatureEngine: maintains rolling market state and emits a per-bar snapshot.

Core signal features are computed on *closed* 5m klines so that live and backtest
produce identical results on the same bars. Live-only streams (order book spread,
liquidations) enrich the snapshot but the bar-based features stand alone.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from common.interfaces import (
    AggTrade,
    Kline,
    Liquidation,
    MarkPrice,
    OpenInterest,
    OrderBook,
)
from features import indicators as ind
from features.liquidations import LiquidationTracker


@dataclass
class FeatureSnapshot:
    timestamp: float
    close: float
    # breakout
    prior_high_1h: float | None
    prior_high_2h: float | None
    breakout: bool
    breakout_level: float | None
    # order flow
    cvd_cum: float
    cvd_slope: float | None
    bar_volume_delta: float
    taker_buy_ratio: float
    price_change_pct: float | None   # close change over cvd_window (for "absorbed selling")
    # open interest / funding
    open_interest: float | None
    oi_change_pct: float | None
    funding_rate: float | None   # None when funding is unknown (don't treat as supportive)
    # volatility / liquidity
    atr: float | None
    realized_vol: float | None
    spread_bps: float | None
    # liquidations (live only)
    short_liq_notional: float
    # trend filter
    trend_sma: float | None = None
    trend_ok: bool = True       # close above trend SMA (no downtrend); True until SMA is available


class FeatureEngine:
    def __init__(self, params: dict) -> None:
        f = params["features"]
        self._lb1 = int(f["breakout_lookback_bars"])
        self._lb2 = int(f["breakout_lookback_bars_2"])
        self._cvd_window = int(f["cvd_window_bars"])
        self._oi_window = int(f["oi_window_bars"])
        self._vol_window = int(f["vol_window_bars"])
        self._trend_window = int(f.get("trend_window_bars", 48))
        self._liq_lookback_s = int(f["liquidation_lookback_s"])

        # deque must hold the longest lookback (+1 for rolling_high/atr that exclude/need a prior bar)
        maxlen = max(self._lb2, self._cvd_window, self._oi_window,
                     self._vol_window, self._trend_window) + 2
        self._highs: deque[float] = deque(maxlen=maxlen)
        self._lows: deque[float] = deque(maxlen=maxlen)
        self._closes: deque[float] = deque(maxlen=maxlen)
        self._cvd_series: deque[float] = deque(maxlen=maxlen)
        self._oi_series: deque[float] = deque(maxlen=maxlen)

        self._cvd_cum = 0.0
        self._latest_spread_bps: float | None = None
        self._latest_funding: float | None = None   # unknown until a mark-price update arrives
        self._latest_oi: float | None = None
        self._liq = LiquidationTracker(self._liq_lookback_s)

    # live enrichment streams
    def on_orderbook(self, ob: OrderBook) -> None:
        if ob.spread_bps is not None:
            self._latest_spread_bps = ob.spread_bps

    def on_mark_price(self, m: MarkPrice) -> None:
        if m.funding_rate is not None:   # only update when funding is actually known
            self._latest_funding = m.funding_rate

    def on_open_interest(self, oi: OpenInterest) -> None:
        self._latest_oi = oi.open_interest

    def on_liquidation(self, liq: Liquidation) -> None:
        self._liq.on_liquidation(liq)

    def on_agg_trade(self, t: AggTrade) -> None:
        # Reserved for intra-bar refinement; core CVD is bar-based for live/backtest parity.
        pass

    # main per-bar computation
    def on_kline(self, k: Kline) -> FeatureSnapshot | None:
        if not k.closed:
            return None
        self._highs.append(k.high)
        self._lows.append(k.low)
        self._closes.append(k.close)
        self._cvd_cum += k.volume_delta
        self._cvd_series.append(self._cvd_cum)
        self._oi_series.append(self._latest_oi if self._latest_oi is not None else float("nan"))

        prior_high_1h = ind.rolling_high(list(self._highs), self._lb1)
        prior_high_2h = ind.rolling_high(list(self._highs), self._lb2)
        breakout = ind.is_breakout(k.close, prior_high_1h)

        cvd_slope = ind.slope(list(self._cvd_series), min(self._cvd_window, len(self._cvd_series) - 1)) \
            if len(self._cvd_series) > 1 else None

        oi_clean = [v for v in self._oi_series if v == v]  # drop NaN
        oi_change_pct = ind.pct_change(oi_clean, self._oi_window) if len(oi_clean) > self._oi_window else None

        atr = ind.atr(list(self._highs), list(self._lows), list(self._closes), self._vol_window)
        rvol = ind.realized_vol(list(self._closes), self._vol_window)
        price_change_pct = ind.pct_change(list(self._closes), self._cvd_window) \
            if len(self._closes) > self._cvd_window else None

        trend_sma = ind.sma(list(self._closes), self._trend_window)
        trend_ok = True if trend_sma is None else k.close >= trend_sma

        return FeatureSnapshot(
            timestamp=float(k.close_time),
            close=k.close,
            prior_high_1h=prior_high_1h,
            prior_high_2h=prior_high_2h,
            breakout=breakout,
            breakout_level=prior_high_1h,
            cvd_cum=self._cvd_cum,
            cvd_slope=cvd_slope,
            bar_volume_delta=k.volume_delta,
            taker_buy_ratio=k.taker_buy_ratio,
            price_change_pct=price_change_pct,
            open_interest=self._latest_oi,
            oi_change_pct=oi_change_pct,
            funding_rate=self._latest_funding,
            atr=atr,
            realized_vol=rvol,
            spread_bps=self._latest_spread_bps,
            short_liq_notional=self._liq.short_liq_notional(float(k.close_time)),
            trend_sma=trend_sma,
            trend_ok=trend_ok,
        )