"""Order request / execution event structures shared by live and simulated paths."""
from __future__ import annotations

from dataclasses import dataclass

from common.enums import OrderStatus, OrderType, Side


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    price: float | None = None          # required for LIMIT
    reduce_only: bool = False           # True for exit orders
    client_order_id: str | None = None
    reason: str = ""                     # human-readable reason (entry/stop/tp/time)


@dataclass
class OrderEvent:
    #Execution report — emitted on fills, cancels and rejections
    timestamp: float
    symbol: str
    side: Side
    status: OrderStatus
    price: float                         # fill price (0 if not filled)
    quantity: float                      # filled quantity
    order_id: str | None = None
    client_order_id: str | None = None
    fee: float = 0.0
    reason: str = ""                     # rejection reason or order tag

    @property
    def is_fill(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) and self.quantity > 0