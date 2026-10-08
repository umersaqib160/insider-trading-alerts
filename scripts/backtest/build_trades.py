"""Backtest part 1: rebuild Q1 2026 insider trades from SEC's Form 345 data set and score them.

Scores with the app's real scoring code (current rules), then computes the proposed rules
(S&P size tiers for buys; cluster bonus only for officers/directors, $10K+ each, tiered by
combined value) alongside. Writes bt.db (a copy of live.db) and trades.json.
Usage: python build_trades.py <data_dir> <live.db> <out_dir>
"""
import csv
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

data_dir, live_db, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
bt_db = out_dir / "bt.db"
shutil.copy(live_db, bt_db)

import os
os.environ["DATABASE_URL"] = f"sqlite:///{bt_db}"
from sqlalchemy import delete, select  # noqa: E402
from app.agents.scout.scoring import CLUSTER_WINDOW_DAYS, score_trades  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.models import (  # noqa: E402
    BUY, SELL, SOURCE_FORM4, Alert, Company, InsiderTradeDetail, ProcessedFiling, Trade,
)
from app.sec import person_name, _tidy_case  # noqa: E402

csv.field_size_limit(10**9)


def rows(name):
    with open(data_dir / name, newline="", encoding="utf-8", errors="replace") as f:
        yield from csv.DictReader(f, delimiter="\t")


def d(s):
    return datetime.strptime(s, "%d-%b-%Y").date()


subs = {}
for r in rows("SUBMISSION.tsv"):
    if r["DOCUMENT_TYPE"] == "4":
        subs[r["ACCESSION_NUMBER"]] = r

owners = defaultdict(list)
for r in rows("REPORTINGOWNER.tsv"):
    if r["ACCESSION_NUMBER"] in subs:
        owners[r["ACCESSION_NUMBER"]].append(r)

totals = {}
for r in rows("NONDERIV_TRANS.tsv"):
    acc, code = r["ACCESSION_NUMBER"], r["TRANS_CODE"]
    if acc not in subs or code not in ("P", "S"):
        continue
    try:
        shares = float(r["TRANS_SHARES"] or 0)
        price = float(r["TRANS_PRICEPERSHARE"]) if r["TRANS_PRICEPERSHARE"] else None
        tdate = d(r["TRANS_DATE"])
    except ValueError:
        continue
    if shares <= 0:
        continue
    t = totals.setdefault((acc, code), {"shares": 0.0, "priced": 0.0, "value": 0.0, "date": tdate, "after": None})
    t["shares"] += shares
    if price:
        t["priced"] += shares
        t["value"] += shares * price
    t["date"] = min(t["date"], tdate)
    if r["SHRS_OWND_FOLWNG_TRANS"]:
        t["after"] = float(r["SHRS_OWND_FOLWNG_TRANS"])


def title(owner):
    rel = owner["RPTOWNER_RELATIONSHIP"] or ""
    parts = []
    if "Officer" in rel:
        parts.append(_tidy_case(owner["RPTOWNER_TITLE"] or "") or "Officer")
    if "Director" in rel:
        parts.append("Director")
    if "TenPercentOwner" in rel:
        parts.append("10% Owner")
    if not parts and "Other" in rel:
        parts.append(owner["RPTOWNER_TXT"] or "Insider")
    return ", ".join(parts)


Session = get_sessionmaker()
db = Session()
db.execute(delete(Alert))
db.execute(delete(InsiderTradeDetail))
db.execute(delete(Trade))
db.execute(delete(ProcessedFiling))
db.commit()

companies = {int(c.cik): c for c in db.scalars(select(Company).where(Company.listed.is_(True))) if c.cik}
# SEC's ticker file is ordered by company size; companies were inserted in that order, so id order = size order.
sp_rank = {c.id: i for i, c in enumerate(
    db.scalars(select(Company).where(Company.in_sp500.is_(True)).order_by(Company.id)), 1)}

seen = set()
trades = []
for (acc, code), t in sorted(totals.items()):
    sub = subs[acc]
    company = companies.get(int(sub["ISSUERCIK"] or 0))
    if not company or not owners[acc]:
        continue
    avg = t["value"] / t["priced"] if t["priced"] else None
    value = avg * t["shares"] if avg else None
    key = (company.id, code, t["date"], round(t["shares"]), round(avg or 0, 2))
    if key in seen:  # co-filed duplicate
        continue
    seen.add(key)
    names = [person_name(o["RPTOWNERNAME"]) for o in owners[acc]]
    name = names[0] if len(names) == 1 else f"{names[0]} and {len(names) - 1} other{'s' if len(names) > 2 else ''}"
    trade = Trade(source=SOURCE_FORM4, external_id=f"{acc}:{code}", company_id=company.id, ticker=company.ticker,
                  asset_name=company.name, actor_name=name, actor_role=title(owners[acc][0]),
                  direction=BUY if code == "P" else SELL, value_low=value, value_high=value, trade_date=t["date"],
                  filed_date=d(sub["FILING_DATE"]), source_url="", tags=[])
    trade.insider = InsiderTradeDetail(accession_no=acc, transaction_code=code, shares=t["shares"], avg_price=avg,
                                       shares_owned_after=t["after"], is_10b5_1=(sub["AFF10B5ONE"] or "").lower() in ("1", "true"))
    db.add(trade)
    trades.append(trade)
db.commit()
print(f"{len(trades)} trades ({sum(t.is_buy for t in trades)} buys) on listed companies")

for i in range(0, len(trades), 500):
    score_trades(db, trades[i:i + 500], watchlist=set())
# Re-score everything once all trades exist, so clusters see the whole quarter.
for i in range(0, len(trades), 500):
    batch = trades[i:i + 500]
    score_trades(db, batch, watchlist=set())


# ---------- proposed rules ----------
def is_officer_or_director(role):
    return any(p.strip() not in ("10% Owner", "") for p in role.split(","))


buys_by_company = defaultdict(list)
for t in trades:
    if t.is_buy:
        buys_by_company[t.company_id].append(t)


def proposed_cluster(t):
    window = timedelta(days=CLUSTER_WINDOW_DAYS)
    group = [b for b in buys_by_company[t.company_id]
             if abs((b.trade_date - t.trade_date).days) <= window.days
             and is_officer_or_director(b.actor_role) and (b.value_low or 0) >= 10_000]
    people = {b.actor_name for b in group}
    total = sum(b.value_low or 0 for b in group)
    if len(people) < 3 or total < 250_000:
        return 0, len(people), total
    return (25 if total >= 1_000_000 else 15), len(people), total


def sp_tier(t):
    rank = sp_rank.get(t.company_id)
    if not t.is_buy or rank is None:
        return 0, rank
    return (15 if rank <= 100 else 10 if rank <= 200 else 5), rank


out = []
for t in trades:
    raw = sum(tag["points"] for tag in t.tags)
    old_cluster = sum(tag["points"] for tag in t.tags if "insiders buying" in tag["label"])
    new_cluster, people, cluster_total = proposed_cluster(t) if t.is_buy else (0, 0, 0)
    bonus, rank = sp_tier(t)
    proposed = min(100, raw - old_cluster + new_cluster + bonus)
    out.append({
        "id": t.id, "ticker": t.ticker, "company": t.asset_name, "buy": t.is_buy, "role": t.actor_role,
        "name": t.actor_name, "value": t.value_low, "trade_date": t.trade_date.isoformat(),
        "filed": t.filed_date.isoformat(), "planned": t.insider.is_10b5_1, "held": t.needs_review,
        "current": t.score, "proposed": proposed, "old_cluster": old_cluster, "new_cluster": new_cluster,
        "cluster_people": people, "cluster_total": cluster_total, "sp_rank": rank, "sp_bonus": bonus,
        "tags": [tag["label"] for tag in t.tags],
    })
(out_dir / "trades.json").write_text(json.dumps(out))
top_sp = [c.ticker for c in db.scalars(select(Company).where(Company.in_sp500.is_(True)).order_by(Company.id).limit(12))]
print("S&P rank check, first 12 by SEC order:", " ".join(top_sp))
print("notable now:", sum(o["current"] >= 60 for o in out), "| notable proposed:", sum(o["proposed"] >= 60 for o in out))
