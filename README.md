# BTCUSDT Short-Squeeze Momentum — Live Paper Trading System

A real-time, event-driven algorithmic trading system that detects **short-squeeze-driven
momentum** in BTCUSDT and paper-trades it on the **Binance USD-Futures testnet**.

Built for the QF635 Algorithmic Trading project. It is a full trading system — not just a
backtest — covering the three graded components:

| Component | Where | What it does |
|-----------|-------|--------------|
| **Analytic** | `features/` | Breakout + CVD + open interest + funding + liquidations + spread/volatility → a composite squeeze signal |
| **Risk** | `risk/` | Vol-targeted sizing, position/leverage caps, drawdown kill-switch, VaR, pre-trade checks |
| **Execution** | `execution/`, `gateway/` | Places paper orders on testnet; manages stop / take-profit / time-stop exits |

A live **dashboard** (`dashboard/`) and an event-driven **backtester** (`backtest/`) complete the project.

## The idea

A naive breakout ("buy the new high") is not an edge. We only trade breakouts that look like a
genuine **short squeeze** — shorts being forced to cover:

1. **Short build-up** — open interest rising while price stays flat, negative/falling funding, sell pressure absorbed.
2. **Squeeze trigger** — price breaks the rolling 1-hour high (and the market is liquid enough to trade).
3. **Forced-cover confirmation** — CVD turns up, taker-buy ratio spikes, **short liquidations fire**, price holds above the breakout.

Entry requires *build-up → trigger → confirmation* to align, and (when
`signal.use_trend_filter` is on) price must be above its trend SMA so the long-only
strategy stands down in a confirmed downtrend. See `features/signal.py`.

**Exits / risk control.** The stop is anchored *below the reclaimed breakout level*
(`breakout_level − stop_atr_mult·ATR`): a fall back below the level **is** the invalidation,
so the ATR stop is the single real risk control (no separate soft exit pre-empts it). Take-profit
is an R-multiple of that stop distance; a time stop and a momentum-fade exit also apply. See
`strategy/squeeze_strategy.py`.

**Capital.** The brief specifies 100k. The backtest uses `account.initial_capital: 100000`
(`config/params.yaml`); the Binance testnet demo account is locked at ~5k, so when running live
the system **auto-syncs** initial capital to the real testnet balance (`account.sync_live_balance`)
so equity, PnL, sizing and VaR reflect reality.

## Architecture

```
Binance Futures Testnet (ws + REST)
        │
   Gateway ──► TradingEngine ──► FeatureEngine ─► SqueezeSignal ─► SqueezeStrategy
   (live or       │                                                      │
    simulated)    ├── PositionManager  (PnL, equity)                     ▼
                  ├── RiskManager      (sizing, kill-switch, VaR) ◄── OrderManager
                  └── DashboardPublisher ──► StateSink (file | redis) ──► Dash reader (separate process)
```

The **same** engine/strategy/risk code runs live (`BinanceFuturesGateway`) and in backtest
(`SimulatedGateway`), so what you test is what you trade.

**Decoupled dashboard.** The engine publishes a state snapshot through a `StateSink`; the Dash
app runs as a **separate process** that reads from the same sink (no API keys, can run on another
machine). The kill-switch also flows through the sink. Backend is config-selectable:
- `dashboard.sink: file` — JSON files in `state/` (one host / one VM).
- `dashboard.sink: redis` — Redis keys (`REDIS_URL` env) for cross-machine / cloud hosting.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then add your Binance testnet API key/secret
```

Get free testnet keys + paper balance at <https://testnet.binancefuture.com>.

> Run all commands from the project root using `python -m ...` so imports resolve.

## Usage

**Backtest (no keys needed — uses synthetic or cached real data):**
```bash
python -m backtest.run_backtest --synthetic              # quick offline demo
python -m scripts.download_all --days 30                 # download real history
python -m backtest.run_backtest --symbol BTCUSDT         # backtest on real data
python -m backtest.run_backtest --symbol BTCUSDT --split 0.7   # walk-forward (in/out-of-sample)
```
Compares **Squeeze (OF-confirmed)** vs **Naive breakout** vs **Buy & hold**.

**Live paper trading + dashboard (two processes):**
```bash
python -m scripts.run_live          # engine: streams testnet, publishes state via the sink
python -m scripts.run_dashboard     # dashboard reader at http://136.110.51.155:8050/
```

**See the dashboard WITHOUT the live engine (no keys):** replay data into the sink, then open the reader.
```bash
python -m scripts.run_demo --synthetic --delay 0.3   # animated, ~live-looking (Ctrl+C to stop)
python -m scripts.run_demo --synthetic               # instant fill, then a static view
python -m scripts.run_dashboard                      # in another terminal -> http://136.110.51.155:8050/
```

## Repository layout

```
common/      config, enums, normalized market-data & order structures
gateway/     base interface + live Binance gateway + simulated (backtest) gateway
features/    indicators, liquidation tracker, feature engine, composite signal
strategy/    squeeze strategy (entry + exit management)
risk/        position manager, sizing, VaR, risk manager (kill-switch, pre-trade checks)
execution/   order manager (risk-checked order submission)
engine/      trading engine (router; live == backtest code path)
dashboard/   sink (file/redis) + publisher + Dash reader app
data/        historical downloaders + synthetic data generator
backtest/    metrics, benchmarks, runner
scripts/     run_live (engine), run_dashboard (reader), download_all
tests/       unit tests (indicators, signal, position, risk, backtest)
config/      params.yaml (all tunables)
```

## Known limitations (state on slides)

- **Liquidation history is not available via REST** (live stream only), so the backtest omits the
  liquidation confirmation sub-signal; the other three confirmation conditions still apply.
- Open-interest history is limited to ~30 days.
- Testnet liquidity is thin, so live fills are not representative of mainnet — the backtest on real
  data is the credible performance estimate; the live system demonstrates the real-time pipeline.
- PnL is not the grading target; this project is graded on analytic, risk, and execution design.