"""Performance metrics from an equity curve and trade list."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

BARS_PER_YEAR_5M = 365 * 24 * 12  # 105,120


@dataclass
class Metrics:
    total_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    hit_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    final_equity: float = 0.0
    extra: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "Total Return": f"{self.total_return:.2%}",
            "Sharpe": f"{self.sharpe:.2f}",
            "Sortino": f"{self.sortino:.2f}",
            "Max DD": f"{self.max_drawdown:.2%}",
            "Trades": self.num_trades,
            "Hit Rate": f"{self.hit_rate:.1%}",
            "Profit Factor": f"{self.profit_factor:.2f}",
            "Final Equity": f"${self.final_equity:,.0f}",
        }


def _max_drawdown(equity: list[float]) -> float:
    peak = -math.inf
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def compute(equity: list[float], trades: list[dict],
            bars_per_year: int = BARS_PER_YEAR_5M) -> Metrics:
    if len(equity) < 2:
        return Metrics()
    rets = [(equity[i] - equity[i - 1]) / equity[i - 1]
            for i in range(1, len(equity)) if equity[i - 1] > 0]
    mean = sum(rets) / len(rets) if rets else 0.0
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    downside = [r for r in rets if r < 0]
    dstd = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    ann = math.sqrt(bars_per_year)
    sharpe = (mean / std * ann) if std > 0 else 0.0
    sortino = (mean / dstd * ann) if dstd > 0 else 0.0

    # `trades` are completed round-trips (one entry->exit each), so count them directly
    pnls = [t.get("realized_pnl", 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    hit = len(wins) / len(pnls) if pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (math.inf if wins else 0.0)

    return Metrics(
        total_return=(equity[-1] - equity[0]) / equity[0],
        sharpe=sharpe, sortino=sortino, max_drawdown=_max_drawdown(equity),
        num_trades=len(pnls), hit_rate=hit,
        avg_win=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        profit_factor=profit_factor, final_equity=equity[-1],
    )