"""Backtest part 2: daily adjusted closes from Yahoo Finance for every ticker in trades.json, plus SPY and IWM (benchmarks).
Caches each ticker in prices/<ticker>.json so reruns resume. Usage: python fetch_prices.py <out_dir>
Prices start 2 weeks before the quarter's first filing. To share one cache across quarters, make
<out_dir>/prices a symlink to a common folder; a cached series that starts too late is fetched again.
"""
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

out = Path(sys.argv[1])
cache = out / "prices"
cache.mkdir(exist_ok=True)
trades = json.loads((out / "trades.json").read_text())
tickers = sorted({t["ticker"] for t in trades} | {"SPY", "IWM"})
first = date.fromisoformat(min(t["filed"] for t in trades))
start = int(datetime(first.year, first.month, 1, tzinfo=timezone.utc).timestamp()) - 86400 * 14
end = int(time.time()) + 86400
need = time.strftime("%Y-%m-%d", time.gmtime(start + 86400 * 10))  # a series starting after this is too short


def cached(path):
    if not path.exists():
        return False
    series = json.loads(path.read_text())
    return not series or min(series) <= need
client = httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})
done = failed = throttled = 0
for i, ticker in enumerate(tickers):
    path = cache / f"{ticker}.json"
    if cached(path):
        continue
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.replace('.', '-')}"
    for attempt in range(6):
        try:
            r = client.get(url, params={"period1": start, "period2": end, "interval": "1d"})
        except httpx.HTTPError:
            time.sleep(5)
            continue
        if r.status_code == 429:
            throttled += 1
            time.sleep(5 * 2 ** min(attempt, 3))
            continue
        break
    series = {}
    try:
        res = r.json()["chart"]["result"][0]
        closes = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or res["indicators"]["quote"][0]["close"]
        for ts, c in zip(res["timestamp"], closes):
            if c:
                series[time.strftime("%Y-%m-%d", time.gmtime(ts))] = c
        done += 1
    except Exception:
        failed += 1
    path.write_text(json.dumps(series))
    if i % 100 == 0:
        print(f"{i}/{len(tickers)} fetched, {failed} without data, {throttled} throttled", flush=True)
    time.sleep(0.25)
print(f"done: {done} with prices, {failed} without, {len(tickers)} tickers")
