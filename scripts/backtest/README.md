# Scoring backtest

Checks whether the notable score picks insider trades that actually moved the
right way afterwards. Uses SEC's quarterly insider data sets (Form 3/4/5) and
daily prices from Yahoo Finance.

All downloads go in `data/backtest/`, which git ignores.

```bash
Q=2026q1
mkdir -p data/backtest/$Q/raw data/backtest/$Q/out
curl -A "Behind The Curtain you@example.com" -o data/backtest/$Q/raw.zip \
  https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/${Q}_form345.zip
unzip -q data/backtest/$Q/raw.zip -d data/backtest/$Q/raw

# 1. Rebuild the quarter's buys/sells and score them (current + proposed rules). Needs a
#    database with the listed-company list loaded (python -m app.cli load-refdata).
PYTHONPATH=. .venv/bin/python scripts/backtest/build_trades.py data/backtest/$Q/raw dev.db data/backtest/$Q/out

# 2. Daily prices for every ticker, plus SPY and IWM. Resumable: cached per ticker.
.venv/bin/python scripts/backtest/fetch_prices.py data/backtest/$Q/out

# 3. Market-adjusted moves 1 week / 1 month / 3 months / 6 months after the filing date, by group.
.venv/bin/python scripts/backtest/analyze.py data/backtest/$Q/out
```

How the analysis works (two views; the stock's own price is the main one):
- **Entry point:** the close on the first trading day after the filing date, which is when a user could first act on the alert.
- **Own price (main view):** did the stock rise after a buy, or fall after a sell?
- **Benchmark (second view):** the same move minus the S&P 500 (SPY) for S&P members or the Russell 2000 (IWM) for everyone else.
- **What's reported:** medians and the share of trades that went the right way (the stock beat its benchmark after a buy, or trailed it after a sell).

Notes and caveats:
- **Compare groups with each other, not with zero.** A typical small stock's median return trails its index, because the index is driven by a few big winners.
- **Proposed rules** are written out in `build_trades.py` (`proposed_cluster`, `sp_tier`), so they can be tested before going into `app/agents/scout/scoring.py`.
- **The S&P size rank** comes from the order of SEC's `company_tickers_exchange.json`, which follows market value. It was checked: NVDA, AAPL, GOOGL, MSFT and AMZN come first.
- **The fetch scripts** need to restart if a long run gets cut off. They resume where they stopped.

Results so far: [`docs/backtest-2026q1.md`](../../docs/backtest-2026q1.md).
