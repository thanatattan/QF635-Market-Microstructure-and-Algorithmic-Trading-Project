"""Order management: pre-trade risk checks, submit to gateway, route fills.

Works identically for live and simulated gateways because both implement
Gateway.place_order(OrderRequest) -> OrderEvent.
"""
from __future__ import annotations

import itertools
import logging

from common.enums import OrderStatus, OrderType, Side
from common.events import OrderEvent, OrderRequest
from gateway.base import Gateway
from risk.position_manager import PositionManager
from risk.risk_manager import RiskManager

log = logging.getLogger("execution")


class OrderManager:
    def __init__(self, gateway: Gateway, position_manager: PositionManager,
                 risk_manager: RiskManager, params: dict) -> None:
        self._gw = gateway
        self._pm = position_manager
        self._rm = risk_manager
        self._order_type = OrderType[params["live"]["order_type"]]
        self._symbol = params["symbol"]
        self._ids = itertools.count(1)
        self.last_rejection: str = ""

    def _coid(self, tag: str) -> str:
        return f"sq-{tag}-{next(self._ids)}"

    def enter(self, side: Side, qty: float, ref_price: float, reason: str = "entry") -> OrderEvent | None:
        """Open/add to a position after pre-trade risk checks."""
        intended_notional = qty * ref_price
        ok, why = self._rm.pre_trade_check(intended_notional, self._pm.equity, self._pm.position_notional)
        if not ok:
            self.last_rejection = why
            log.warning("Entry blocked by risk: %s", why)
            return None
        req = OrderRequest(symbol=self._symbol, side=side, order_type=self._order_type,
                           quantity=qty, reduce_only=False,
                           client_order_id=self._coid("ent"), reason=reason)
        return self._submit(req)

    def close(self, reason: str = "exit") -> OrderEvent | None:
        """Flatten the current position with a reduce-only market order (always allowed)."""
        pos = self._pm.position
        if pos == 0:
            return None
        side = Side.SELL if pos > 0 else Side.BUY
        req = OrderRequest(symbol=self._symbol, side=side, order_type=OrderType.MARKET,
                           quantity=abs(pos), reduce_only=True,
                           client_order_id=self._coid("cls"), reason=reason)
        return self._submit(req)

    def _submit(self, req: OrderRequest) -> OrderEvent:
        ev = self._gw.place_order(req)
        if ev.status is OrderStatus.REJECTED:
            self.last_rejection = ev.reason
            log.warning("Order rejected: %s", ev.reason)
        elif ev.is_fill:
            self._pm.on_fill(ev)
            log.info("FILL %s %.4f @ %.2f (%s) pos=%.4f",
                     ev.side.value, ev.quantity, ev.price, ev.reason, self._pm.position)
        return ev