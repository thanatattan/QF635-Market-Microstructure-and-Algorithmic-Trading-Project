"""Abstract gateway interface.

Both the live Binance gateway and the simulated (backtest) gateway implement this,
so the TradingEngine / strategy / risk code is identical in live and backtest.

The gateway is a *source of events*: callers register callbacks and the gateway
invokes them as market data and executions arrive.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from common.events import OrderEvent, OrderRequest
from common.interfaces import (
    AggTrade,
    Kline,
    Liquidation,
    MarkPrice,
    OpenInterest,
    OrderBook,
)

@dataclass
class SymbolFilters:
    # Exchange precision rules for a symbol (from exchangeInfo)
    tick_size: float            # price increment
    step_size: float            # quantity increment
    min_notional: float

    def round_price(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, 8)

    def round_qty(self, qty: float) -> float:
        # floor to step size; +epsilon counters float-division error
        # (e.g. 0.167/0.001 == 166.9999996 -> would wrongly floor to 166, leaving dust)
        steps = int(qty / self.step_size + 1e-9)
        return round(steps * self.step_size, 8)


class Gateway(ABC):
    # Base class providing the callback registry; subclasses provide connectivity

    def __init__(self) -> None:
        self._on_kline: list[Callable[[Kline], None]] = []
        self._on_agg_trade: list[Callable[[AggTrade], None]] = []
        self._on_orderbook: list[Callable[[OrderBook], None]] = []
        self._on_mark_price: list[Callable[[MarkPrice], None]] = []
        self._on_liquidation: list[Callable[[Liquidation], None]] = []
        self._on_open_interest: list[Callable[[OpenInterest], None]] = []
        self._on_execution: list[Callable[[OrderEvent], None]] = []

    # callback registration
    def register_kline(self, cb: Callable[[Kline], None]) -> None:
        self._on_kline.append(cb)

    def register_agg_trade(self, cb: Callable[[AggTrade], None]) -> None:
        self._on_agg_trade.append(cb)

    def register_orderbook(self, cb: Callable[[OrderBook], None]) -> None:
        self._on_orderbook.append(cb)

    def register_mark_price(self, cb: Callable[[MarkPrice], None]) -> None:
        self._on_mark_price.append(cb)

    def register_liquidation(self, cb: Callable[[Liquidation], None]) -> None:
        self._on_liquidation.append(cb)

    def register_open_interest(self, cb: Callable[[OpenInterest], None]) -> None:
        self._on_open_interest.append(cb)

    def register_execution(self, cb: Callable[[OrderEvent], None]) -> None:
        self._on_execution.append(cb)

    # dispatch helpers (used by subclasses)
    def _emit_kline(self, k: Kline) -> None:
        for cb in self._on_kline:
            cb(k)

    def _emit_agg_trade(self, t: AggTrade) -> None:
        for cb in self._on_agg_trade:
            cb(t)

    def _emit_orderbook(self, ob: OrderBook) -> None:
        for cb in self._on_orderbook:
            cb(ob)

    def _emit_mark_price(self, m: MarkPrice) -> None:
        for cb in self._on_mark_price:
            cb(m)

    def _emit_liquidation(self, liq: Liquidation) -> None:
        for cb in self._on_liquidation:
            cb(liq)

    def _emit_open_interest(self, oi: OpenInterest) -> None:
        for cb in self._on_open_interest:
            cb(oi)

    def _emit_execution(self, ev: OrderEvent) -> None:
        for cb in self._on_execution:
            cb(ev)

    # lifecycle & orders
    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def get_filters(self) -> SymbolFilters:
        ...

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderEvent:
        # Submit an order. Returns an immediate ack/event; fills also arrive via the execution callback
        ...

    @abstractmethod
    def cancel_all(self) -> None:
        ...