"""Shared enumerations used across market data, orders and signals."""
from __future__ import annotations

from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        #+1 for BUY, -1 for SELL — convenient for signed position math
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class SignalState(str, Enum):
    """High-level state of the squeeze pipeline, surfaced on the dashboard."""
    IDLE = "IDLE"                # nothing interesting
    BUILDUP = "BUILDUP"          # short build-up detected, waiting for trigger
    TRIGGERED = "TRIGGERED"      # breakout fired, waiting for forced-cover confirmation
    CONFIRMED = "CONFIRMED"      # full squeeze signal -> entry
    IN_POSITION = "IN_POSITION"  # holding a position, managing exits