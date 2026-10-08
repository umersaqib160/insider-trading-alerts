"""Backtest part 4: pool several quarters and check which scoring signals hold up.

Reads each quarter's trades.json and prices (built by build_trades.py and fetch_prices.py), measures
moves the same way as analyze.py, and prints:
  1. pooled groups (own-price view first, then index view), with how many quarters each group beat the
     quarter's all-buys (or all-sells) median at 6 months, which shows how stable a signal is;
  2. a regression of "went the right way at 6 months" on all buy signals at once, with quarter fixed
     effects, so each signal is measured with the others held constant (e.g. CEO vs director at equal size);
  3. score buckets for the current rules and for candidate new weights (CANDIDATE below).
Size check without hindsight: besides today's S&P 500 rank, buys are ranked by each company's public
float as of the June before the trade (SEC XBRL frames, data/backtest/float/CY<year>Q2I.json).
Usage: python pool.py <db> <out_dir> [<out_dir> ...]   (writes pooled.json next to the first out_dir's parent)
"""
import bisect
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

db_path, dirs = sys.argv[1], [Path(p) for p in sys.argv[2:]]
root = dirs[0].parent.parent
HORIZONS = {"1m": 21, "3m": 63, "6m": 126}

con = sqlite3.connect(db_path)
cik_by_ticker = {t: int(c) for t, c in con.execute("select ticker, cik from companies where cik is not null")}


def float_ranks(year):
    path = root / "float" / f"CY{year}Q2I.json"
    if not path.exists():
        return {}
    rows = sorted(json.loads(path.read_text())["data"], key=lambda r: -r["val"])
    return {r["cik"]: i for i, r in enumerate(rows, 1)}


floats = {}
price_cache = {}


def load(prices_dir, ticker):
    if ticker not in price_cache:
        path = prices_dir / f"{ticker}.json"
        series = json.loads(path.read_text()) if path.exists() else {}
        price_cache[ticker] = (sorted(series), series) if len(series) > 30 else None
    return price_cache[ticker]


def role(t):
    r = t["role"].lower()
    if "chief executive" in r or " ceo" in f" {r}" or "chief financial" in r or " cfo" in f" {r}" or ("chair" in r and "vice chair" not in r):
        return "top"
    if any(p.strip() not in ("Director", "10% Owner", "") for p in t["role"].split(",")):
        return "officer"
    if "Director" in t["role"]:
        return "director"
    return "ten"


def size(v):
    v = v or 0
    return "<100K" if v < 1e5 else "100K-1M" if v < 1e6 else "1M-5M" if v < 5e6 else "5M-10M" if v < 1e7 else "10M+"


def sp(t):
    r = t["sp_rank"]
    return "out" if not r else "1-100" if r <= 100 else "101-200" if r <= 200 else "201-500"


def pit(t):
    r = t["float_rank"]
    return "unknown" if r is None else "1-100" if r <= 100 else "101-200" if r <= 200 else "201-500" if r <= 500 else "501-1000" if r <= 1000 else "1000+"


# ---------- candidate weights (what the proposal would score) ----------
CANDIDATE = {
    "buy": 25, "unplanned_sale": 0, "planned_sale": 0,
    "size": [(1e7, 10), (1e6, 8), (1e5, 4)],
    "role": {"top": 8, "officer": 10, "director": 12, "ten": 0},
    "sp": {"1-100": 25, "101-200": 25, "201-500": 0, "out": 0},
    "cluster": {15: 15, 25: 25},
}


def candidate_score(t):
    w = CANDIDATE
    s = w["buy"] if t["buy"] else (w["planned_sale"] if t["planned"] else w["unplanned_sale"])
    s += next((p for v, p in w["size"] if (t["value"] or 0) >= v), 0)
    s += w["role"][role(t)]
    if t["buy"]:
        s += w["sp"][sp(t)] + w["cluster"].get(t["new_cluster"], 0)
    return min(100, s)


trades = []
for out in dirs:
    quarter = out.parent.name
    year = int(quarter[:4])
    if year - 1 not in floats:
        floats[year - 1] = float_ranks(year - 1)
    prices = out / "prices"
    spy_days, spy = load(prices, "SPY")
    iwm_days, iwm = load(prices, "IWM")
    for t in json.loads((out / "trades.json").read_text()):
        t["q"] = quarter
        t["float_rank"] = floats[year - 1].get(cik_by_ticker.get(t["ticker"]))
        t["cand"] = candidate_score(t)
        t["own"], t["ret"] = {}, {}
        trades.append(t)
        loaded = load(prices, t["ticker"])
        if not loaded or t["held"]:
            continue
        days, px = loaded
        i = bisect.bisect_right(days, t["filed"])
        if i >= len(days):
            continue
        entry = days[i]
        bench_days, bench = (spy_days, spy) if t["sp_rank"] else (iwm_days, iwm)
        j = bisect.bisect_left(bench_days, entry)
        if j >= len(bench_days) or bench_days[j] != entry:
            continue
        for name, n in HORIZONS.items():
            if i + n < len(days) and j + n < len(bench_days):
                stock = px[days[i + n]] / px[entry] - 1
                t["own"][name] = stock
                t["ret"][name] = stock - (bench[bench_days[j + n]] / bench[entry] - 1)
    price_cache.clear()

quarters = [d.parent.name for d in dirs]
buys = [t for t in trades if t["buy"] and not t["held"] and "6m" in t["own"]]
sells = [t for t in trades if not t["buy"] and not t["held"] and "6m" in t["own"]]


def signed(t, key, h):
    return t[key][h] if t["buy"] else -t[key][h]


def stats(group, key="own", h="6m"):
    vals = [signed(t, key, h) for t in group if h in t[key]]
    if len(vals) < 5:
        return None
    return {"n": len(vals), "median": statistics.median(vals), "hit": sum(v > 0 for v in vals) / len(vals)}


def stability(group, base, key="own"):
    """Quarters where the group's 6-month median beat the baseline's, out of quarters with 10+ trades."""
    by_q, base_q = defaultdict(list), defaultdict(list)
    for t in group:
        by_q[t["q"]].append(signed(t, key, "6m"))
    for t in base:
        base_q[t["q"]].append(signed(t, key, "6m"))
    usable = [q for q in quarters if len(by_q[q]) >= 10]
    wins = sum(statistics.median(by_q[q]) > statistics.median(base_q[q]) for q in usable)
    return wins, len(usable)


def bucket(score):
    return "0-19" if score < 20 else "20-39" if score < 40 else "40-59" if score < 60 else "60-79" if score < 80 else "80+"


groups = {"All buys": buys}
for label in ("0-19", "20-39", "40-59", "60-79", "80+"):
    groups[f"Buys, current score {label}"] = [t for t in buys if bucket(t["current"]) == label]
groups["Buys, notable today (60+)"] = [t for t in buys if t["current"] >= 60]
groups["Buys, notable with build_trades proposal"] = [t for t in buys if t["proposed"] >= 60]
for label in ("0-19", "20-39", "40-59", "60-79", "80+"):
    groups[f"Buys, candidate score {label}"] = [t for t in buys if bucket(t["cand"]) == label]
groups["Buys, notable with candidate weights"] = [t for t in buys if t["cand"] >= 60]
for label in ("<100K", "100K-1M", "1M-5M", "5M-10M", "10M+"):
    groups[f"Buys {label}"] = [t for t in buys if size(t["value"]) == label]
for key, label in (("top", "CEO/CFO/Chair"), ("officer", "other officers"), ("director", "directors"), ("ten", "10% owners only")):
    groups[f"Buys by {label}"] = [t for t in buys if role(t) == key]
for label in ("1-100", "101-200", "201-500", "out"):
    groups[f"Buys, S&P 500 today {label}"] = [t for t in buys if sp(t) == label]
for label in ("1-100", "101-200", "201-500", "501-1000", "1000+", "unknown"):
    groups[f"Buys, size rank at the time {label}"] = [t for t in buys if pit(t) == label]
groups["Buys, old cluster rule"] = [t for t in buys if t["old_cluster"]]
groups["Buys, old cluster only (token buys / funds)"] = [t for t in buys if t["old_cluster"] and not t["new_cluster"]]
groups["Buys, new cluster +15 ($250K-$1M)"] = [t for t in buys if t["new_cluster"] == 15]
groups["Buys, new cluster +25 ($1M+)"] = [t for t in buys if t["new_cluster"] == 25]
groups["Buys, no cluster"] = [t for t in buys if not t["old_cluster"] and not t["new_cluster"]]

sell_groups = {"All sells": sells,
               "Sells, pre-planned (10b5-1)": [t for t in sells if t["planned"]],
               "Sells, unplanned": [t for t in sells if not t["planned"]]}
for label in ("<100K", "100K-1M", "1M-5M", "5M-10M", "10M+"):
    sell_groups[f"Sells {label}"] = [t for t in sells if size(t["value"]) == label]
for key, label in (("top", "CEO/CFO/Chair"), ("officer", "other officers"), ("director", "directors"), ("ten", "10% owners only")):
    sell_groups[f"Sells by {label}"] = [t for t in sells if role(t) == key]
for label in ("0-19", "20-39", "40-59", "60-79", "80+"):
    sell_groups[f"Sells, current score {label}"] = [t for t in sells if bucket(t["current"]) == label]


def table(gs, base, key):
    rows = {}
    print(f"{'group':48} {'n':>6} | {'3m med':>7} {'3m rt':>5} | {'6m med':>7} {'6m rt':>5} | stable")
    for name, g in gs.items():
        s3, s6 = stats(g, key, "3m"), stats(g, key, "6m")
        wins, of = stability(g, base, key)
        rows[name] = {"n": len(g), "3m": s3, "6m": s6, "stable": [wins, of]}
        if not s6:
            print(f"{name:48} {len(g):6d} |   (too few)")
            continue
        print(f"{name:48} {len(g):6d} | {s3['median']*100:+6.1f}% {s3['hit']*100:4.0f}% | "
              f"{s6['median']*100:+6.1f}% {s6['hit']*100:4.0f}% | {wins:2d}/{of}")
    return rows


print(f"quarters: {', '.join(quarters)}")
print(f"trades: {len(trades)}; with 6-month prices: {len(buys)} buys, {len(sells)} sells "
      f"(held excluded: {sum(t['held'] for t in trades)})")
result = {}
for key, title in (("own", "AGAINST ITS OWN PRICE (main view)"), ("ret", "AGAINST ITS BENCHMARK (S&P 500 or Russell 2000)")):
    print(f"\n=== {title}; 'rt' = share that went the insider's way; 'stable' = quarters beating the baseline median ===")
    result[key] = {"buys": table(groups, buys, key), "sells": table(sell_groups, sells, key)}

# ---------- per quarter ----------
per_q = {}
print("\n=== PER QUARTER, own price, 6 months: median / share that rose (n) ===")
key_groups = ["All buys", "Buys, notable today (60+)", "Buys, notable with candidate weights",
              "Buys, S&P 500 today 1-100", "Buys, S&P 500 today 101-200", "Buys, S&P 500 today 201-500",
              "Buys, size rank at the time 1-100", "Buys, size rank at the time 101-200",
              "Buys by CEO/CFO/Chair", "Buys by directors", "Buys by 10% owners only", "Buys 1M-5M", "Buys 10M+",
              "Buys, new cluster +15 ($250K-$1M)", "Buys, new cluster +25 ($1M+)"]
all_groups = {**groups, **sell_groups}
for name in key_groups + ["All sells", "Sells, unplanned"]:
    cells, per_q[name] = [], {}
    for q in quarters:
        s = stats([t for t in all_groups[name] if t["q"] == q])
        per_q[name][q] = s
        cells.append(f"{s['median']*100:+5.0f}/{s['hit']*100:3.0f}%({s['n']})" if s else "      —      ")
    print(f"{name[:40]:40} " + " ".join(cells))
result["per_quarter"] = per_q

# ---------- regression ----------
# Linear probability model: rose_6m (buys) ~ signals + quarter fixed effects. Coefficient = change in the share
# that rose, in points, versus the reference group (an "other officer" buy under $100K outside the S&P, no cluster).
features = {
    "CEO/CFO/Chair": lambda t: role(t) == "top", "Director": lambda t: role(t) == "director",
    "10% owner only": lambda t: role(t) == "ten",
    "$100K-$1M": lambda t: size(t["value"]) == "100K-1M", "$1M-$5M": lambda t: size(t["value"]) == "1M-5M",
    "$5M-$10M": lambda t: size(t["value"]) == "5M-10M", "$10M+": lambda t: size(t["value"]) == "10M+",
    "S&P today 1-100": lambda t: sp(t) == "1-100", "S&P today 101-200": lambda t: sp(t) == "101-200",
    "S&P today 201-500": lambda t: sp(t) == "201-500",
    "Old cluster only": lambda t: bool(t["old_cluster"]) and not t["new_cluster"],
    "New cluster +15": lambda t: t["new_cluster"] == 15, "New cluster +25": lambda t: t["new_cluster"] == 25,
}


def inverse(m):
    """Gauss-Jordan inverse of a small square matrix (lists of floats)."""
    n = len(m)
    a = [row[:] + [float(i == j) for j in range(n)] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        pivot = a[c][c]
        a[c] = [v / pivot for v in a[c]]
        for r in range(n):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [v - f * w for v, w in zip(a[r], a[c])]
    return [row[n:] for row in a]


def regress(rows, feats, target):
    feats = {n: f for n, f in feats.items() if sum(map(f, rows)) >= 20}  # skip signals with too few trades
    names = list(feats) + quarters[1:]
    X = [[1.0] + [float(f(t)) for f in feats.values()] + [float(t["q"] == q) for q in quarters[1:]] for t in rows]
    y = [float(target(t)) for t in rows]
    k = len(X[0])
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    xty = [sum(x[i] * v for x, v in zip(X, y)) for i in range(k)]
    inv = inverse(xtx)
    beta = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    resid2 = [(v - sum(b * xi for b, xi in zip(beta, x))) ** 2 for x, v in zip(X, y)]
    # Heteroskedasticity-robust (HC1) standard errors: inv * (X' diag(e^2) X) * inv.
    meat = [[sum(x[i] * x[j] * e for x, e in zip(X, resid2)) for j in range(k)] for i in range(k)]
    half = [[sum(inv[i][m] * meat[m][j] for m in range(k)) for j in range(k)] for i in range(k)]
    scale = len(y) / (len(y) - k)
    se = [(sum(half[i][m] * inv[m][i] for m in range(k)) * scale) ** 0.5 for i in range(k)]
    return {n: (beta[i + 1], se[i + 1]) for i, n in enumerate(names) if n in feats}


reg = {}
for label, target in (("rose_6m", lambda t: t["own"]["6m"] > 0), ("beat_index_6m", lambda t: t["ret"]["6m"] > 0)):
    print(f"\n=== REGRESSION ({label}), buys: points vs an officer's <$100K buy outside the S&P, no cluster ===")
    reg[label] = regress(buys, features, target)
    for name, (b, se) in reg[label].items():
        flag = "**" if abs(b) > 2.6 * se else "*" if abs(b) > 2 * se else ""
        print(f"  {name:22} {b*100:+6.1f} pts  (±{se*100*2:.1f}) {flag}")
    # Same with size at the time instead of today's S&P list (no hindsight).
    pit_feats = {k: v for k, v in features.items() if not k.startswith("S&P")}
    pit_feats |= {"Size rank then 1-100": lambda t: pit(t) == "1-100", "Size rank then 101-200": lambda t: pit(t) == "101-200",
                  "Size rank then 201-500": lambda t: pit(t) == "201-500", "Size rank then 501-1000": lambda t: pit(t) == "501-1000"}
    reg[label + "_pit"] = regress(buys, pit_feats, target)
    print("  -- with size rank at the time instead of today's S&P list:")
    for name in ("Size rank then 1-100", "Size rank then 101-200", "Size rank then 201-500", "Size rank then 501-1000"):
        if name not in reg[label + "_pit"]:
            continue
        b, se = reg[label + "_pit"][name]
        print(f"  {name:22} {b*100:+6.1f} pts  (±{se*100*2:.1f})")
result["regression"] = {k: {n: list(v) for n, v in r.items()} for k, r in reg.items()}
(root / "pooled.json").write_text(json.dumps(result, indent=1, default=float))
