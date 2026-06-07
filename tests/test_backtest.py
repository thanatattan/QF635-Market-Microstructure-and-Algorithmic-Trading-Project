from backtest import benchmarks
from data import synthetic


def test_engine_backtest_runs(params):
    df = synthetic.generate(n_bars=1500, seed=1)
    metrics, equity = benchmarks.run_engine_backtest(df, params, signal_mode="full")
    assert len(equity) > 0
    assert metrics.final_equity > 0
    # the synthetic data engineers squeeze episodes -> strategy should take some trades
    assert metrics.num_trades >= 1


def test_backtest_deterministic(params):
    df = synthetic.generate(n_bars=1000, seed=7)
    m1, _ = benchmarks.run_engine_backtest(df, params, signal_mode="full")
    m2, _ = benchmarks.run_engine_backtest(df, params, signal_mode="full")
    assert m1.final_equity == m2.final_equity
    assert m1.num_trades == m2.num_trades


def test_buy_and_hold_runs(params):
    df = synthetic.generate(n_bars=500)
    m, equity = benchmarks.buy_and_hold(df, params)
    assert len(equity) == len(df)