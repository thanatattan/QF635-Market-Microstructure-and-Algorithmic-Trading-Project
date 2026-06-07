"""Live Binance USD-M Futures *testnet* gateway.

Streams market data over websockets and places paper orders via REST, converting
everything to the normalized structures in common/. Designed for the testnet
(testnet.binancefuture.com) — paper trading with a fake balance.
"""
from __future__ import annotations

import logging
import threading
import time

from binance import Client, ThreadedWebsocketManager

from common.config import Credentials
from common.enums import OrderStatus, OrderType, Side
from common.events import OrderEvent, OrderRequest
from common.interfaces import (
    AggTrade,
    Kline,
    Liquidation,
    MarkPrice,
    OpenInterest,
    OrderBook,
    PriceLevel,
)
from gateway.base import Gateway, SymbolFilters

log = logging.getLogger("gateway.binance")


class BinanceFuturesGateway(Gateway):
    def __init__(self, symbol: str, credentials: Credentials, params: dict) -> None:
        super().__init__()
        self.symbol = symbol.upper()
        self._cred = credentials
        self._params = params
        self._taker_fee = float(params["account"]["taker_fee"])
        self._oi_poll_s = int(params["live"]["oi_poll_seconds"])
        self._stale_s = int(params["live"].get("ws_stale_seconds", 90))
        self._client: Client | None = None
        self._twm: ThreadedWebsocketManager | None = None
        self._filters: SymbolFilters | None = None
        self._oi_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._streams: list[str] = []
        self._conn_key = None
        self._last_msg_time: float = 0.0
        self._running = False

    # lifecycle
    def start(self) -> None:
        if not self._cred.is_configured:
            raise RuntimeError(
                "Binance testnet API key/secret not configured. Copy .env.example to .env "
                "and fill in BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET."
            )
        self._client = Client(self._cred.api_key, self._cred.api_secret, testnet=True)
        self._filters = self._load_filters()
        self._set_leverage()

        self._twm = ThreadedWebsocketManager(
            api_key=self._cred.api_key, api_secret=self._cred.api_secret, testnet=True
        )
        self._twm.start()

        interval = self._params["bar_interval"]
        s = self.symbol.lower()
        streams = [
            f"{s}@kline_{interval}",
            f"{s}@aggTrade",
            f"{s}@bookTicker",
            f"{s}@markPrice@1s",
            f"{s}@forceOrder",
        ]
        self._streams = streams
        self._conn_key = self._twm.start_futures_multiplex_socket(callback=self._on_ws, streams=streams)
        self._last_msg_time = time.time()

        self._running = True
        self._oi_thread = threading.Thread(target=self._poll_open_interest, name="oi-poll", daemon=True)
        self._oi_thread.start()
        self._watchdog_thread = threading.Thread(target=self._watchdog, name="ws-watchdog", daemon=True)
        self._watchdog_thread.start()
        log.info("BinanceFuturesGateway started for %s (testnet) streams=%s", self.symbol, streams)

    def stop(self) -> None:
        self._running = False
        if self._twm is not None:
            try:
                self._twm.stop()
            except Exception:  # noqa: BLE001
                pass
        log.info("BinanceFuturesGateway stopped")

    def get_filters(self) -> SymbolFilters:
        assert self._filters is not None, "Gateway not started"
        return self._filters

    def fetch_usdt_balance(self) -> float | None:
        """Return the real USDT futures balance (testnet demo is locked at ~5k).

        Creates a temporary client if the gateway hasn't started yet, so the engine
        can be seeded with the true balance before the PositionManager is built.
        """
        if not self._cred.is_configured:
            return None
        try:
            client = self._client or Client(self._cred.api_key, self._cred.api_secret, testnet=True)
            for b in client.futures_account_balance():
                if b["asset"] == "USDT":
                    return float(b["balance"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not fetch testnet balance: %s", exc)
        return None

    # setup helpers
    def _load_filters(self) -> SymbolFilters:
        info = self._client.futures_exchange_info()
        sym = next(x for x in info["symbols"] if x["symbol"] == self.symbol)
        tick = step = notional = None
        for f in sym["filters"]:
            if f["filterType"] == "PRICE_FILTER":
                tick = float(f["tickSize"])
            elif f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
            elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                notional = float(f.get("notional", f.get("minNotional", 5.0)))
        return SymbolFilters(tick_size=tick or 0.1, step_size=step or 0.001, min_notional=notional or 5.0)

    def _set_leverage(self) -> None:
        try:
            lev = int(self._params["risk"]["max_leverage"])
            self._client.futures_change_leverage(symbol=self.symbol, leverage=max(lev, 1))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not set leverage: %s", exc)

    # websocket dispatch
    def _on_ws(self, msg: dict) -> None:
        self._last_msg_time = time.time()
        try:
            # python-binance signals socket errors with an 'e':'error' frame
            if isinstance(msg, dict) and msg.get("e") == "error":
                log.warning("Websocket error frame: %s", msg)
                return
            stream = msg.get("stream", "")
            data = msg.get("data", msg)
            if "@kline" in stream:
                self._handle_kline(data)
            elif "@aggTrade" in stream:
                self._handle_agg_trade(data)
            elif "@bookTicker" in stream:
                self._handle_book_ticker(data)
            elif "@markPrice" in stream:
                self._handle_mark_price(data)
            elif "@forceOrder" in stream:
                self._handle_force_order(data)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error handling ws message: %s", exc)

    def _handle_kline(self, data: dict) -> None:
        k = data["k"]
        self._emit_kline(Kline(
            open_time=int(k["t"]), close_time=int(k["T"]),
            open=float(k["o"]), high=float(k["h"]), low=float(k["l"]), close=float(k["c"]),
            volume=float(k["v"]), num_trades=int(k["n"]), taker_buy_volume=float(k["V"]),
            closed=bool(k["x"]),
        ))

    def _handle_agg_trade(self, data: dict) -> None:
        self._emit_agg_trade(AggTrade(
            timestamp=float(data["T"]), price=float(data["p"]),
            qty=float(data["q"]), is_buyer_maker=bool(data["m"]),
        ))

    def _handle_book_ticker(self, data: dict) -> None:
        ts = float(data.get("T", data.get("E", time.time() * 1000)))
        ob = OrderBook(
            timestamp=ts, symbol=self.symbol,
            bids=[PriceLevel(float(data["b"]), float(data["B"]))],
            asks=[PriceLevel(float(data["a"]), float(data["A"]))],
        )
        self._emit_orderbook(ob)

    def _handle_mark_price(self, data: dict) -> None:
        self._emit_mark_price(MarkPrice(
            timestamp=float(data["E"]), mark_price=float(data["p"]),
            funding_rate=float(data["r"]), next_funding_time=int(data["T"]),
        ))

    def _handle_force_order(self, data: dict) -> None:
        o = data["o"]
        price = float(o.get("ap") or o["p"])
        self._emit_liquidation(Liquidation(
            timestamp=float(o["T"]), side=Side(o["S"]), price=price, qty=float(o["q"]),
        ))

    # reconnect watchdog
    def _watchdog(self) -> None:
        """Restart the market-data socket if no message arrives for `ws_stale_seconds`."""
        check_every = max(self._stale_s // 3, 5)
        while self._running:
            time.sleep(check_every)
            if not self._running:
                break
            if time.time() - self._last_msg_time > self._stale_s:
                log.warning("No ws data for >%ds — restarting market-data socket", self._stale_s)
                try:
                    if self._conn_key is not None:
                        self._twm.stop_socket(self._conn_key)
                except Exception as exc:  # noqa: BLE001
                    log.warning("stop_socket failed: %s", exc)
                try:
                    self._conn_key = self._twm.start_futures_multiplex_socket(
                        callback=self._on_ws, streams=self._streams)
                    self._last_msg_time = time.time()
                    log.info("Market-data socket restarted")
                except Exception as exc:  # noqa: BLE001
                    log.error("ws restart failed: %s", exc)

    # open interest polling
    def _poll_open_interest(self) -> None:
        while self._running:
            try:
                resp = self._client.futures_open_interest(symbol=self.symbol)
                self._emit_open_interest(OpenInterest(
                    timestamp=time.time() * 1000, open_interest=float(resp["openInterest"]),
                ))
            except Exception as exc:  # noqa: BLE001
                log.warning("OI poll failed: %s", exc)
            time.sleep(self._oi_poll_s)

    # orders
    def place_order(self, request: OrderRequest) -> OrderEvent:
        assert self._client is not None and self._filters is not None
        qty = self._filters.round_qty(request.quantity)
        if qty <= 0:
            return OrderEvent(
                timestamp=time.time() * 1000, symbol=self.symbol, side=request.side,
                status=OrderStatus.REJECTED, price=0.0, quantity=0.0,
                reason="quantity rounds to zero",
            )
        kwargs = dict(
            symbol=self.symbol, side=request.side.value,
            type=request.order_type.value, quantity=qty, newOrderRespType="RESULT",
        )
        if request.reduce_only:
            kwargs["reduceOnly"] = "true"
        if request.order_type is OrderType.LIMIT:
            kwargs["price"] = self._filters.round_price(request.price)
            kwargs["timeInForce"] = "GTC"
        try:
            resp = self._client.futures_create_order(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("Order rejected by exchange: %s", exc)
            return OrderEvent(
                timestamp=time.time() * 1000, symbol=self.symbol, side=request.side,
                status=OrderStatus.REJECTED, price=0.0, quantity=0.0, reason=str(exc),
            )
        executed_qty = float(resp.get("executedQty", 0.0))
        avg_price = float(resp.get("avgPrice", 0.0)) or (request.price or 0.0)
        fee = avg_price * executed_qty * self._taker_fee
        status = OrderStatus(resp.get("status", "NEW")) if resp.get("status") in OrderStatus._value2member_map_ else OrderStatus.NEW
        ev = OrderEvent(
            timestamp=time.time() * 1000, symbol=self.symbol, side=request.side,
            status=status, price=avg_price, quantity=executed_qty,
            order_id=str(resp.get("orderId")), client_order_id=request.client_order_id,
            fee=fee, reason=request.reason,
        )
        self._emit_execution(ev)
        return ev

    def cancel_all(self) -> None:
        if self._client is not None:
            try:
                self._client.futures_cancel_all_open_orders(symbol=self.symbol)
            except Exception as exc:  # noqa: BLE001
                log.warning("cancel_all failed: %s", exc)