"""Backtest part 2: daily adjusted closes from Yahoo Finance for every ticker in trades.json, plus SPY and IWM (benchmarks).
Caches each ticker in prices/<ticker>.json so reruns resume. Usage: python fetch_prices.py <out_dir>
"""
import json
import sys
import time
from pathlib import Path

import httpx

out = Path(sys.argv[1])
cache = out / "prices"
cache.mkdir(exist_ok=True)
tickers = sorted({t["ticker"] for t in json.loads((out / "trades.json").read_text())} | {"SPY", "IWM"})
start, end = 1767225600, 1760054400 + 86400 * 400  # 2026-01-01 .. well past today
client = httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})
done = failed = 0
for i, ticker in enumerate(tickers):
    path = cache / f"{ticker}.json"
    if path.exists():
        continue
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.replace('.', '-')}"
    for attempt in range(3):
        try:
            r = client.get(url, params={"period1": start, "period2": end, "interval": "1d"})
        except httpx.HTTPError:
            time.sleep(5)
            continue
        if r.status_code == 429:
            time.sleep(30)
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
    if i % 200 == 0:
        print(f"{i}/{len(tickers)} fetched, {failed} without data", flush=True)
    time.sleep(0.25)
print(f"done: {done} with prices, {failed} without, {len(tickers)} tickers")
