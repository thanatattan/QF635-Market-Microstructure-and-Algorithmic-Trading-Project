"""Simulated gateway for backtesting.

Replays a historical DataFrame through the *same* engine callbacks the live
gateway uses, so the strategy / risk / position code is identical. Market orders
fill immediately at the current bar close adjusted for slippage.

Expected DataFrame columns (one row per closed 5m bar, time-ordered):
    open_time, close_time, open, high, low, close, volume, num_trades,
    taker_buy_volume, open_interest (optional), funding_rate (optional)

Liquidations are NOT available historically, so the @forceOrder stream is not
replayed — the strategy's confirmation logic degrades gracefully (documented).
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from common.enums import OrderStatus, Side
from common.events import OrderEvent, OrderRequest
from common.interfaces import (
    Kline,
    MarkPrice,
    OpenInterest,
    OrderBook,
    PriceLevel,
)
from gateway.base import Gateway, SymbolFilters

log = logging.getLogger("gateway.sim")


class SimulatedGateway(Gateway):
    def __init__(self, symbol: str, data: pd.DataFrame, params: dict, bar_delay: float = 0.0) -> None:
        super().__init__()
        self.symbol = symbol.upper()
        self._data = data.reset_index(drop=True)
        self._bar_delay = bar_delay   # seconds to sleep between bars (0 = as fast as possible)
        self._taker_fee = float(params["account"]["taker_fee"])
        self._slippage_bps = float(params["account"]["slippage_bps"])
        self._filters = SymbolFilters(tick_size=0.1, step_size=0.001, min_notional=5.0)
        self._last_close: float = 0.0
        self._last_ts: float = 0.0
        # orders decided on bar T fill at bar T+1's open (conservative, no look-ahead)
        self._fill_price: float = 0.0

    def get_filters(self) -> SymbolFilters:
        return self._filters

    def start(self) -> None:
        # Run the full replay synchronously, then return
        log.info("SimulatedGateway replaying %d bars for %s", len(self._data), self.symbol)
        has_oi = "open_interest" in self._data.columns
        has_funding = "funding_rate" in self._data.columns
        # next-bar open for each bar (last bar falls back to its own close)
        next_opens = self._data["open"].shift(-1).tolist()
        for i, row in enumerate(self._data.itertuples(index=False)):
            self._last_close = float(row.close)
            self._last_ts = float(row.close_time)
            nxt = next_opens[i]
            self._fill_price = float(nxt) if nxt == nxt else float(row.close)  # nan-safe

            if has_oi and not pd.isna(getattr(row, "open_interest")):
                self._emit_open_interest(OpenInterest(
                    timestamp=self._last_ts, open_interest=float(row.open_interest)))

            funding = float(getattr(row, "funding_rate")) if has_funding and not pd.isna(getattr(row, "funding_rate")) else None
            self._emit_mark_price(MarkPrice(
                timestamp=self._last_ts, mark_price=self._last_close,
                funding_rate=funding, next_funding_time=0))

            # synthetic tight book so the spread/liquidity gate passes in backtest
            half = self._last_close * (self._slippage_bps / 1e4)
            self._emit_orderbook(OrderBook(
                timestamp=self._last_ts, symbol=self.symbol,
                bids=[PriceLevel(self._last_close - half, 1.0)],
                asks=[PriceLevel(self._last_close + half, 1.0)]))

            self._emit_kline(Kline(
                open_time=int(row.open_time), close_time=int(row.close_time),
                open=float(row.open), high=float(row.high), low=float(row.low),
                close=float(row.close), volume=float(row.volume),
                num_trades=int(row.num_trades), taker_buy_volume=float(row.taker_buy_volume),
                closed=True))
            if self._bar_delay:
                time.sleep(self._bar_delay)
        log.info("SimulatedGateway replay complete")

    def stop(self) -> None:
        pass

    def place_order(self, request: OrderRequest) -> OrderEvent:
        qty = self._filters.round_qty(request.quantity)
        if qty <= 0:
            return OrderEvent(timestamp=self._last_ts, symbol=self.symbol, side=request.side,
                              status=OrderStatus.REJECTED, price=0.0, quantity=0.0,
                              reason="quantity rounds to zero")
        ref = self._fill_price or self._last_close   # next-bar open (fallback to close)
        slip = ref * (self._slippage_bps / 1e4)
        fill_price = ref + slip if request.side is Side.BUY else ref - slip
        fee = fill_price * qty * self._taker_fee
        ev = OrderEvent(timestamp=self._last_ts, symbol=self.symbol, side=request.side,
                        status=OrderStatus.FILLED, price=fill_price, quantity=qty,
                        fee=fee, client_order_id=request.client_order_id, reason=request.reason)
        self._emit_execution(ev)
        return ev

    def cancel_all(self) -> None:
        pass