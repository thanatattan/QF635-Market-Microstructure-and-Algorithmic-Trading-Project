"""Composite squeeze-signal logic.

Turns a FeatureSnapshot into a trade decision following the team's thesis:
    short build-up  ->  breakout trigger  ->  forced-cover confirmation  ->  enter.

The engine is stateful only to remember whether short build-up occurred within the
last N bars (build-up must precede the breakout).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from common.enums import SignalState
from features.engine import FeatureSnapshot


@dataclass
class SignalDecision:
    state: SignalState
    enter: bool
    tradable: bool
    buildup_score: int
    confirm_score: int
    breakout_level: float | None
    trend_ok: bool = True
    buildup_conditions: dict[str, bool] = field(default_factory=dict)
    confirm_conditions: dict[str, bool] = field(default_factory=dict)
    reason: str = ""


class SqueezeSignalEngine:
    def __init__(self, params: dict) -> None:
        f = params["features"]
        s = params["signal"]
        self._oi_rise_pct = float(f["oi_rise_pct"])
        self._funding_max = float(f["funding_buildup_max"])
        self._taker_confirm = float(f["taker_buy_confirm"])
        self._liq_min = float(f["liquidation_min_notional"])
        self._spread_max = float(f["spread_max_bps"])
        self._buildup_lookback = int(s["buildup_lookback_bars"])
        self._min_buildup = int(s["min_buildup_score"])
        self._min_confirm = int(s["min_confirm_score"])
        # "full" = squeeze pipeline; "naive_breakout" = breakout only (benchmark)
        self._mode = s.get("mode", "full")
        self._use_trend_filter = bool(s.get("use_trend_filter", True))
        self._use_oi = bool(s.get("use_oi", True))   # OI history is ~30d; turn off for long backtests
        self._bars_since_buildup = 10**9   # large = "no recent build-up"

    def evaluate(self, snap: FeatureSnapshot) -> SignalDecision:
        # liquidity / tradability gate
        tradable = snap.spread_bps is None or snap.spread_bps <= self._spread_max

        # short build-up sub-conditions. OI is optional (history only ~30 days), so it is
        # only included when use_oi is on — otherwise build-up = funding + absorbed-selling.
        b_funding = snap.funding_rate is not None and snap.funding_rate <= self._funding_max
        b_absorbed = (
            snap.cvd_slope is not None and snap.cvd_slope <= 0
            and snap.price_change_pct is not None and snap.price_change_pct >= -0.002
        )
        buildup_conditions = {"funding_support": b_funding, "sell_absorbed": b_absorbed}
        if self._use_oi:
            b_oi = snap.oi_change_pct is not None and snap.oi_change_pct >= self._oi_rise_pct
            buildup_conditions = {"oi_rising": b_oi, **buildup_conditions}
        buildup_score = sum(buildup_conditions.values())
        buildup_now = buildup_score >= self._min_buildup

        if buildup_now:
            self._bars_since_buildup = 0
        else:
            self._bars_since_buildup += 1
        buildup_recent = self._bars_since_buildup <= self._buildup_lookback

        # forced-cover confirmation (4 sub-conditions)
        # NOTE: "price holds above the level" is NOT counted here — it is already guaranteed by
        # the breakout gate below, so counting it would double-count and weaken the threshold.
        # Real confirmations: CVD up, taker-buy dominance, short-liquidation burst.
        # Backtest has no liquidation feed (short_liq always False), so min_confirm=2 means it
        # needs cvd_up AND taker_buy; live can satisfy any 2 of the 3.
        c_cvd = snap.bar_volume_delta > 0 or (snap.cvd_slope is not None and snap.cvd_slope > 0)
        c_taker = snap.taker_buy_ratio >= self._taker_confirm
        c_liq = snap.short_liq_notional >= self._liq_min
        confirm_conditions = {"cvd_up": c_cvd, "taker_buy": c_taker, "short_liq": c_liq}
        confirm_score = sum(confirm_conditions.values())
        confirmed = confirm_score >= self._min_confirm

        # trend filter (don't buy breakouts in a downtrend)
        trend_gate = (not self._use_trend_filter) or snap.trend_ok

        # entry decision
        if self._mode == "naive_breakout":
            enter = bool(snap.breakout and tradable)   # benchmark: breakout with no order-flow filter
        else:
            enter = bool(snap.breakout and buildup_recent and confirmed and tradable and trend_gate)

        if enter:
            state = SignalState.CONFIRMED
            reason = "squeeze confirmed: build-up + breakout + forced-cover"
        elif snap.breakout:
            state = SignalState.TRIGGERED
            if confirmed and buildup_recent and tradable and not trend_gate:
                reason = "breakout confirmed but blocked by downtrend filter"
            elif not confirmed:
                reason = "breakout fired, awaiting confirmation"
            else:
                reason = "breakout confirmed but not tradable/no recent build-up"
        elif buildup_now:
            state = SignalState.BUILDUP
            reason = "short build-up detected"
        else:
            state = SignalState.IDLE
            reason = "idle"

        return SignalDecision(
            state=state, enter=enter, tradable=tradable,
            buildup_score=buildup_score, confirm_score=confirm_score,
            breakout_level=snap.breakout_level, trend_ok=snap.trend_ok,
            buildup_conditions=buildup_conditions, confirm_conditions=confirm_conditions,
            reason=reason,
        )