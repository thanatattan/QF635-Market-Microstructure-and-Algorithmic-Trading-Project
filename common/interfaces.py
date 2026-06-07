"""Normalized market-data structures.

The Gateway converts raw Binance payloads into these so that the rest of the
system (features, strategy, backtest) never touches exchange-specific JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from common.enums import Side


@dataclass
class PriceLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    timestamp: float            # ms epoch
    symbol: str
    bids: list[PriceLevel] = field(default_factory=list)  # descending by price
    asks: list[PriceLevel] = field(default_factory=list)  # ascending by price

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float | None:
        #Bid-ask spread in basis points of mid
        if self.best_bid is None or self.best_ask is None or self.mid in (None, 0):
            return None
        return (self.best_ask - self.best_bid) / self.mid * 1e4

    def imbalance(self, levels: int = 5) -> float | None:
        """Order-book imbalance in [-1, 1]: +1 = all bid depth, -1 = all ask depth."""
        bid_vol = sum(l.size for l in self.bids[:levels])
        ask_vol = sum(l.size for l in self.asks[:levels])
        total = bid_vol + ask_vol
        if total == 0:
            return None
        return (bid_vol - ask_vol) / total


@dataclass
class Kline:
    open_time: int              # ms epoch
    close_time: int             # ms epoch
    open: float
    high: float
    low: float
    close: float
    volume: float               # base-asset volume
    num_trades: int
    taker_buy_volume: float     # base-asset volume from taker BUY (aggressive buys)
    closed: bool                # True only on the candle-close event

    @property
    def taker_sell_volume(self) -> float:
        return max(self.volume - self.taker_buy_volume, 0.0)

    @property
    def taker_buy_ratio(self) -> float:
        #Share of volume that was aggressive buying (buy aggression).
        return self.taker_buy_volume / self.volume if self.volume > 0 else 0.5

    @property
    def volume_delta(self) -> float:
        #Per-bar CVD contribution: taker buy minus taker sell volume.
        return self.taker_buy_volume - self.taker_sell_volume


@dataclass
class AggTrade:
    timestamp: float            # ms epoch
    price: float
    qty: float
    is_buyer_maker: bool        # if True the buyer was the maker -> aggressor SOLD

    @property
    def side(self) -> Side:
        #Aggressor side: buyer_maker == True means an aggressive SELL hit the bid.
        return Side.SELL if self.is_buyer_maker else Side.BUY

    @property
    def signed_qty(self) -> float:
        return self.qty * self.side.sign


@dataclass
class MarkPrice:
    timestamp: float
    mark_price: float
    funding_rate: float         # current (predicted) funding rate
    next_funding_time: int      # ms epoch


@dataclass
class Liquidation:
    """A forced order from the @forceOrder stream.

    NOTE on interpretation (key for the squeeze thesis):
      - side == SELL  -> a LONG position was liquidated (forced selling)
      - side == BUY   -> a SHORT position was liquidated (forced BUYING == a squeeze)
    """
    timestamp: float
    side: Side
    price: float
    qty: float

    @property
    def notional(self) -> float:
        return self.price * self.qty

    @property
    def is_short_liquidation(self) -> bool:
        return self.side is Side.BUY


@dataclass
class OpenInterest:
    timestamp: float
    open_interest: float        # in base asset (BTC)