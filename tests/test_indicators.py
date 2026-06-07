from features import indicators as ind


def test_rolling_high_excludes_current():
    highs = [10, 11, 12, 9]   # lookback 2 over prior bars [11,12] -> 12
    assert ind.rolling_high(highs, 2) == 12


def test_rolling_high_insufficient():
    assert ind.rolling_high([1, 2], 5) is None


def test_is_breakout():
    assert ind.is_breakout(13, 12) is True
    assert ind.is_breakout(12, 12) is False
    assert ind.is_breakout(13, None) is False


def test_atr_positive():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    assert ind.atr(highs, lows, closes, 3) > 0


def test_pct_change():
    assert ind.pct_change([100, 101, 110], 2) == (110 - 100) / 100


def test_slope_direction():
    assert ind.slope([1, 2, 3, 4], 3) > 0
    assert ind.slope([4, 3, 2, 1], 3) < 0