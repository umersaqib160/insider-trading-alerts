from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.agents.scout import approve_trade, run_nightly, run_scout
from app.agents.scout.insiders import (
    ingest_live_feed, prune_processed, recent_business_days, reconcile_days,
)
from app.models import ProcessedFiling, Trade
from app.sec import EdgarError, current_feed_path, daily_index_path, parse_current_feed

from .conftest import FIXTURES
from .form4 import APPLE_CEO_SALE, APPLE_GRANT_ONLY, NVIDIA_DIRECTOR_BUY

MONDAY = date(2026, 9, 28)
FRIDAY = date(2026, 9, 25)


def feed(*entries: tuple[str, str, str, int, str], start: datetime = datetime(2026, 9, 25, 17, 0)) -> str:
    """Atom in SEC's real shape. Each entry: (form, name, role, cik, accession), newest first."""
    items = []
    for i, (form, name, role, cik, accession) in enumerate(entries):
        updated = (start - timedelta(minutes=i)).isoformat() + "-04:00"
        items.append(f"""<entry>
<title>{form} - {name} ({cik:010d}) ({role})</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-09-25 &lt;b&gt;AccNo:&lt;/b&gt; {accession} &lt;b&gt;Size:&lt;/b&gt; 8 KB</summary>
<updated>{updated}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={accession}</id>
</entry>""")
    return f"""<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>{''.join(items)}</feed>"""


SALE, BUY, GRANT = "0001140361-26-000101", "0001045810-26-000202", "0001140361-26-000303"
FEED_PAGE = feed(
    ("4", "Cook Timothy D", "Reporting", 1214156, SALE),
    ("4", "Apple Inc.", "Issuer", 320193, SALE),
    ("424B2", "Some Bank", "Filer", 70858, "0000070858-26-000001"),
    ("4", "NVIDIA CORP", "Issuer", 1045810, BUY),
    ("4", "Untracked Co", "Issuer", 999999, "0000999999-26-000404"),
    ("4", "Apple Inc.", "Issuer", 320193, GRANT),
)
SUBMISSIONS = {
    f"/Archives/edgar/data/320193/{SALE}.txt": APPLE_CEO_SALE,
    f"/Archives/edgar/data/1045810/{BUY}.txt": NVIDIA_DIRECTOR_BUY,
    f"/Archives/edgar/data/320193/{GRANT}.txt": APPLE_GRANT_ONLY,
}


class FakeEdgar:
    def __init__(self, files: dict[str, str], fail_on: str | None = None):
        self.files = files
        self.fail_on = fail_on
        self.requested: list[str] = []

    def get_text(self, path: str) -> str | None:
        self.requested.append(path)
        if self.fail_on and self.fail_on in path:
            raise EdgarError("SEC EDGAR returned HTTP 503")
        return self.files.get(path)

    def get_json(self, path: str):
        return None


def live_edgar(page: str = FEED_PAGE) -> FakeEdgar:
    return FakeEdgar({current_feed_path(0, 100): page, **SUBMISSIONS})


def companies_by_cik(db) -> dict:
    from app.models import Company
    return {int(c.cik): c for c in db.scalars(select(Company)) if c.cik}


# ---------- SEC live feed ----------

def test_parse_current_feed():
    entries = parse_current_feed(FEED_PAGE)
    assert [e.form for e in entries] == ["4", "4", "424B2", "4", "4", "4"]
    apple = entries[1]
    assert (apple.accession_no, apple.cik, apple.role, apple.filed) == (SALE, 320193, "Issuer", FRIDAY)


def test_live_feed_stores_new_buys_and_sells_once(db, seeded):
    edgar = live_edgar()
    result = ingest_live_feed(db, edgar, companies_by_cik(db))
    assert result.filings == 3  # Apple sale, Nvidia buy, Apple grant; the 424B2 and untracked issuer are skipped
    assert sorted((t.ticker, t.direction) for t in result.trades) == [("AAPL", "sell"), ("NVDA", "buy")]
    sale = db.scalar(select(Trade).where(Trade.ticker == "AAPL"))
    assert (sale.actor_name, sale.actor_role, sale.value_low, sale.value_high) == (
        "Timothy D Cook", "Chief Executive Officer", 1_006_000, 1_006_000)
    assert (sale.insider.shares, sale.insider.is_10b5_1, sale.filed_date) == (4000, True, FRIDAY)
    assert db.scalar(select(func.count()).select_from(ProcessedFiling)) == 3  # the grant is recorded too

    again = ingest_live_feed(db, edgar, companies_by_cik(db))
    assert again.filings == 0
    assert sum(p.endswith(".txt") for p in edgar.requested) == 3


def test_live_feed_reads_further_pages_until_it_reaches_seen_filings(db, seeded):
    newer = feed(("4", "NVIDIA CORP", "Issuer", 1045810, BUY), start=datetime(2026, 9, 25, 17, 30))
    older = feed(("4", "Apple Inc.", "Issuer", 320193, SALE), start=datetime(2026, 9, 25, 17, 25))
    edgar = FakeEdgar({current_feed_path(0, 100): newer, current_feed_path(100, 100): older, **SUBMISSIONS})
    assert ingest_live_feed(db, edgar, companies_by_cik(db)).filings == 2


def test_live_feed_stops_after_an_hour_of_history(db, seeded):
    recent = feed(("4", "Untracked Co", "Issuer", 999999, "x-1"), start=datetime(2026, 9, 25, 17, 0))
    stale = feed(("4", "Untracked Co", "Issuer", 999999, "x-2"), start=datetime(2026, 9, 25, 15, 0))
    edgar = FakeEdgar({current_feed_path(0, 100): recent + "", current_feed_path(100, 100): stale,
                       current_feed_path(200, 100): FEED_PAGE})
    ingest_live_feed(db, edgar, companies_by_cik(db))
    assert current_feed_path(200, 100) not in edgar.requested


def test_reconcile_days_catches_what_the_feed_missed(db, seeded):
    edgar = FakeEdgar({daily_index_path(FRIDAY): (FIXTURES / "form_index_sample.idx").read_text(), **SUBMISSIONS})
    by_cik = companies_by_cik(db)
    ingest_live_feed(db, FakeEdgar({current_feed_path(0, 100): feed(("4", "Apple Inc.", "Issuer", 320193, SALE)),
                                    **SUBMISSIONS}), by_cik)
    result = reconcile_days(db, edgar, by_cik, [date(2026, 9, 24), FRIDAY])
    assert result.unpublished_days == [date(2026, 9, 24)]
    assert [t.ticker for t in result.trades] == ["NVDA"]
    assert f"/Archives/edgar/data/320193/{SALE}.txt" not in edgar.requested  # already read from the feed


def test_recent_business_days_and_pruning(db):
    assert recent_business_days(MONDAY, 3) == [date(2026, 9, 23), date(2026, 9, 24), FRIDAY]
    db.add_all([ProcessedFiling(accession_no="old", filed_date=MONDAY - timedelta(days=40)),
                ProcessedFiling(accession_no="new", filed_date=MONDAY)])
    db.commit()
    assert prune_processed(db, MONDAY) == 1
    assert db.scalar(select(ProcessedFiling.accession_no)) == "new"


# ---------- full runs ----------

class FakeQuiver:
    def __init__(self, rows: list[dict] | None = None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error

    def recent_congress_trades(self) -> list[dict]:
        if self.error:
            raise self.error
        return self.rows


def pelosi_row(**extra) -> dict:
    row = {"Representative": "Nancy Pelosi", "BioGuideID": "P000197", "House": "Representatives",
           "Ticker": "NVDA", "Transaction": "Purchase", "Range": "$1,000,001 - $5,000,000",
           "TransactionDate": "2026-09-02", "ReportDate": "2026-09-25", "Owner": "Spouse"}
    row.update(extra)
    return row


def test_run_scout_end_to_end(db, seeded, telegram):
    from .test_alerts import add_user
    add_user(db, 55, companies=["NVDA"])
    add_user(db, 66, politicians=["P000197"])

    report = run_scout(db, live_edgar(), FakeQuiver([pelosi_row()]), telegram, MONDAY)
    lines = "\n".join(report.lines())
    assert "insiders: 3 new filings, 2 buys/sells" in lines
    assert "congress: 1 new trades" in lines
    assert report.alerts_created == 3  # user 55: Nvidia insider buy + Pelosi's NVDA trade; user 66: Pelosi's trade
    assert sorted(chat for chat, _ in telegram.sent) == [55, 55, 66]
    assert all(t.score > 0 for t in report.new_trades)

    rerun = run_scout(db, live_edgar(), FakeQuiver([pelosi_row()]), telegram, MONDAY)
    assert rerun.new_trades == [] and len(telegram.sent) == 3


def test_run_scout_without_quiver_key_and_with_sec_outage(db, seeded, telegram):
    report = run_scout(db, FakeEdgar({}, fail_on="getcurrent"), None, telegram, MONDAY)
    assert "congress: skipped (QUIVER_API_KEY not set)" in report.lines()
    assert report.errors == ["SEC EDGAR returned HTTP 503"]


def test_held_trades_wait_for_approval(db, seeded, telegram):
    from .test_alerts import add_user
    add_user(db, 55, politicians=["P000197"])
    huge = pelosi_row(Range="Over $50,000,000", Ticker="AAPL")
    report = run_scout(db, FakeEdgar({}), FakeQuiver([huge]), telegram, MONDAY)
    [trade] = report.new_trades
    assert trade.needs_review and "Over $50M" in trade.review_reason
    assert telegram.sent == [] and report.alerts_created == 0

    result = approve_trade(db, trade, telegram, MONDAY)
    assert result.sent == 1 and trade.needs_review is False
    assert run_scout(db, FakeEdgar({}), FakeQuiver([huge]), telegram, MONDAY).alerts_created == 0
    assert trade.needs_review is False  # approval sticks


def test_run_nightly_backfill(db, seeded, telegram):
    edgar = FakeEdgar({daily_index_path(FRIDAY): (FIXTURES / "form_index_sample.idx").read_text(), **SUBMISSIONS})
    report = run_nightly(db, edgar, None, telegram, MONDAY, send_alerts=False, refresh_refdata=False)
    lines = "\n".join(report.lines())
    assert "insiders: 3 filings caught up, 2 buys/sells (no index yet for 2026-09-23, 2026-09-24)" in lines
    assert telegram.sent == []


@pytest.mark.parametrize("quiver_error", ["Quiver refused the API key (HTTP 401)."])
def test_quiver_errors_are_reported_not_fatal(db, seeded, telegram, quiver_error):
    from app.agents.scout.congress import QuiverError
    report = run_scout(db, live_edgar(), FakeQuiver(error=QuiverError(quiver_error)), telegram, MONDAY)
    assert report.errors == [quiver_error]
    assert len(report.new_trades) == 2  # insider trades still processed


def test_interrupted_run_keeps_progress_and_next_run_finishes_it(db, seeded, telegram):
    from .test_alerts import add_user
    add_user(db, 55, companies=["AAPL", "NVDA"])
    edgar = live_edgar()
    edgar.fail_on = GRANT  # SEC stops answering at the third filing
    first = run_scout(db, edgar, None, telegram, MONDAY, send_alerts=False)
    assert first.errors == ["SEC EDGAR returned HTTP 503"]
    assert len(first.new_trades) == 2 and all(t.tags for t in first.new_trades)

    # Simulate a crash after storing but before scoring: the next run must pick these up.
    for t in first.new_trades:
        t.score, t.tags = 0, []
    db.commit()
    edgar.fail_on = None
    second = run_scout(db, edgar, None, telegram, MONDAY)
    assert "picked up 2 trades left unscored by an interrupted run" in second.lines()
    assert second.alerts_created == 2 and len(telegram.sent) == 2


def test_co_filed_duplicates_are_stored_once(db, seeded):
    from .form4 import owner, submission, transaction
    fund = submission("0000000001-26-000001", [transaction("P", "950000", "17.00", "2026-09-24")],
                      [owner("Big Fund LP", ten_percent=True)], issuer_cik="0001045810", ticker="NVDA")
    partner = submission("0000000001-26-000002", [transaction("P", "950000", "17.00", "2026-09-24")],
                         [owner("Partner Jane", director=True)], issuer_cik="0001045810", ticker="NVDA")
    other = submission("0000000001-26-000003", [transaction("P", "61516", "17.00", "2026-09-24")],
                       [owner("Director Erez", director=True)], issuer_cik="0001045810", ticker="NVDA")
    page = feed(*[("4", "NVIDIA CORP", "Issuer", 1045810, f"0000000001-26-00000{i}") for i in (3, 2, 1)])
    edgar = FakeEdgar({current_feed_path(0, 100): page,
                       **{f"/Archives/edgar/data/1045810/0000000001-26-00000{i}.txt": t
                          for i, t in ((1, fund), (2, partner), (3, other))}})
    result = ingest_live_feed(db, edgar, companies_by_cik(db))
    assert result.filings == 3
    assert sorted(t.actor_name for t in result.trades) == ["Erez Director", "Jane Partner"]  # the fund's later copy is skipped
    assert db.scalar(select(func.count()).select_from(Trade)) == 2
