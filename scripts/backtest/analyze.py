"""Backtest part 3: market-adjusted returns after each alert date, by scoring group.

Entry = close of the first trading day after the filing date (when a user could act on the alert).
Excess return = stock return minus SPY return over the same days. "Right direction" = a buy beat
SPY, or a sell trailed it. Medians are used because a few small caps move hundreds of percent.
Usage: python analyze.py <out_dir>
"""
import bisect
import json
import statistics
import sys
from pathlib import Path

out = Path(sys.argv[1])
trades = json.loads((out / "trades.json").read_text())
HORIZONS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126}


def load(ticker):
    path = out / "prices" / f"{ticker}.json"
    if not path.exists():
        return None
    series = json.loads(path.read_text())
    return (sorted(series), series) if len(series) > 30 else None


spy_days, spy = load("SPY")
iwm_days, iwm = load("IWM")
for t in trades:
    t["ret"] = {}
    loaded = load(t["ticker"])
    if not loaded or t["held"]:
        continue
    days, px = loaded
    i = bisect.bisect_right(days, t["filed"])  # first trading day after the filing date
    if i >= len(days):
        continue
    entry_day = days[i]
    # Size-matched benchmark: S&P 500 for S&P members, Russell 2000 (IWM) for everyone else.
    bench_days, bench = (spy_days, spy) if t["sp_rank"] else (iwm_days, iwm)
    j = bisect.bisect_left(bench_days, entry_day)
    for name, n in HORIZONS.items():
        if i + n < len(days) and j + n < len(bench_days) and bench_days[j] == entry_day:
            stock = px[days[i + n]] / px[entry_day] - 1
            market = bench[bench_days[j + n]] / bench[entry_day] - 1
            t["ret"][name] = stock - market


def summary(group):
    res = {"n": len(group)}
    for name in HORIZONS:
        vals = [(t["ret"][name] if t["buy"] else -t["ret"][name]) for t in group if name in t["ret"]]
        if len(vals) < 5:
            res[name] = None
            continue
        res[name] = {
            "n": len(vals),
            "median": statistics.median(vals),
            "hit": sum(v > 0 for v in vals) / len(vals),
            "mean_capped": statistics.mean(max(-1, min(1, v)) for v in vals),
        }
    return res


buys = [t for t in trades if t["buy"] and not t["held"]]
sells = [t for t in trades if not t["buy"] and not t["held"]]


def role(t):
    r = t["role"].lower()
    if "chief executive" in r or " ceo" in f" {r}" or "chief financial" in r or " cfo" in f" {r}" or ("chair" in r and "vice chair" not in r):
        return "top"
    if any(p.strip() not in ("Director", "10% Owner", "") for p in t["role"].split(",")):
        return "officer"
    if "Director" in t["role"]:
        return "director"
    return "ten"


groups = {
    "All buys": buys,
    "All sells": sells,
    "Buys, notable today (60+)": [t for t in buys if t["current"] >= 60],
    "Buys, not notable today": [t for t in buys if t["current"] < 60],
    "Buys, notable with proposed rules": [t for t in buys if t["proposed"] >= 60],
    "Buys, not notable with proposed rules": [t for t in buys if t["proposed"] < 60],
    "Dropped by the proposal (notable before, not after)": [t for t in buys if t["current"] >= 60 > t["proposed"]],
    "Added by the proposal (notable after, not before)": [t for t in buys if t["proposed"] >= 60 > t["current"]],
    "Buys, S&P 500 top 100": [t for t in buys if t["sp_rank"] and t["sp_rank"] <= 100],
    "Buys, S&P 500 101-200": [t for t in buys if t["sp_rank"] and 100 < t["sp_rank"] <= 200],
    "Buys, S&P 500 201-500": [t for t in buys if t["sp_rank"] and t["sp_rank"] > 200],
    "Buys, outside the S&P 500": [t for t in buys if not t["sp_rank"]],
    "Buys in a cluster, kept by new rule": [t for t in buys if t["new_cluster"]],
    "Buys in a cluster, only under old rule (token / funds)": [t for t in buys if t["old_cluster"] and not t["new_cluster"]],
    "Buys, no cluster": [t for t in buys if not t["old_cluster"] and not t["new_cluster"]],
    "Buys by CEO/CFO/Chair": [t for t in buys if role(t) == "top"],
    "Buys by other officers": [t for t in buys if role(t) == "officer"],
    "Buys by directors": [t for t in buys if role(t) == "director"],
    "Buys by 10% owners only": [t for t in buys if role(t) == "ten"],
    "Buys under $100K": [t for t in buys if (t["value"] or 0) < 100_000],
    "Buys $100K-$1M": [t for t in buys if 100_000 <= (t["value"] or 0) < 1_000_000],
    "Buys $1M+": [t for t in buys if (t["value"] or 0) >= 1_000_000],
    "Sells, pre-planned (10b5-1)": [t for t in sells if t["planned"]],
    "Sells, unplanned": [t for t in sells if not t["planned"]],
}
results = {name: summary(g) for name, g in groups.items()}
(out / "results.json").write_text(json.dumps(results, indent=1))

priced = sum(1 for t in trades if t["ret"])
print(f"trades with prices: {priced} of {len(trades)} (held excluded: {sum(t['held'] for t in trades)})")
print(f"{'group':58} {'n':>5} | " + " | ".join(f"{h:^20}" for h in HORIZONS))
print(" " * 64 + " | ".join(f"{'median':>7} {'right':>5} {'n':>5}" for _ in HORIZONS))
for name, res in results.items():
    cells = []
    for h in HORIZONS:
        r = res[h]
        cells.append(f"{r['median']*100:+6.1f}% {r['hit']*100:4.0f}% {r['n']:5d}" if r else f"{'—':>20}")
    print(f"{name:58} {res['n']:5d} | " + " | ".join(cells))
