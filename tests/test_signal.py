from common.enums import SignalState
from features.engine import FeatureSnapshot
from features.signal import SqueezeSignalEngine


def _snap(**kw) -> FeatureSnapshot:
    base = dict(
        timestamp=0.0, close=105.0, prior_high_1h=100.0, prior_high_2h=100.0,
        breakout=True, breakout_level=100.0, cvd_cum=10.0, cvd_slope=1.0,
        bar_volume_delta=5.0, taker_buy_ratio=0.7, price_change_pct=0.0,
        open_interest=1000.0, oi_change_pct=0.02, funding_rate=-0.0002,
        atr=2.0, realized_vol=0.01, spread_bps=2.0, short_liq_notional=100_000.0,
    )
    base.update(kw)
    return FeatureSnapshot(**base)


def test_full_signal_enters_on_confirmed_squeeze(params):
    eng = SqueezeSignalEngine(params)
    # first bar establishes build-up (selling absorbed: cvd flat-ish, price not falling)
    eng.evaluate(_snap(breakout=False, cvd_slope=-1.0, bar_volume_delta=-1.0,
                        taker_buy_ratio=0.45, short_liq_notional=0.0))
    d = eng.evaluate(_snap())  # breakout + confirmation, build-up recent
    assert d.enter is True
    assert d.state is SignalState.CONFIRMED


def test_naive_mode_enters_on_breakout_only(params):
    import copy
    p = copy.deepcopy(params)
    p["signal"]["mode"] = "naive_breakout"
    eng = SqueezeSignalEngine(p)
    d = eng.evaluate(_snap(taker_buy_ratio=0.4, oi_change_pct=-0.05,
                           funding_rate=0.01, short_liq_notional=0.0))
    assert d.enter is True   # breakout alone is enough in naive mode


def test_trend_filter_blocks_long_in_downtrend(params):
    import copy
    p = copy.deepcopy(params)
    p["signal"]["use_trend_filter"] = True
    eng = SqueezeSignalEngine(p)
    eng.evaluate(_snap(breakout=False, cvd_slope=-1.0, bar_volume_delta=-1.0,
                        taker_buy_ratio=0.45, short_liq_notional=0.0, trend_ok=False))
    d = eng.evaluate(_snap(trend_ok=False))   # confirmed squeeze but downtrend
    assert d.enter is False
    assert d.trend_ok is False


def test_trend_filter_off_allows_entry(params):
    import copy
    p = copy.deepcopy(params)
    p["signal"]["use_trend_filter"] = False
    eng = SqueezeSignalEngine(p)
    eng.evaluate(_snap(breakout=False, cvd_slope=-1.0, bar_volume_delta=-1.0,
                        taker_buy_ratio=0.45, short_liq_notional=0.0, trend_ok=False))
    d = eng.evaluate(_snap(trend_ok=False))
    assert d.enter is True   # toggle off -> downtrend doesn't block


def test_no_entry_without_breakout(params):
    eng = SqueezeSignalEngine(params)
    d = eng.evaluate(_snap(breakout=False))
    assert d.enter is False


def test_spread_gate_blocks(params):
    eng = SqueezeSignalEngine(params)
    eng.evaluate(_snap(breakout=False, cvd_slope=-1.0, bar_volume_delta=-1.0, taker_buy_ratio=0.45))
    d = eng.evaluate(_snap(spread_bps=999.0))   # too wide
    assert d.tradable is False
    assert d.enter is False