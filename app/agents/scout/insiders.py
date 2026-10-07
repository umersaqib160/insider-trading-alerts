"""Company insider trades from SEC Form 4 filings."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BUY, SELL, SOURCE_FORM4, Company, InsiderTradeDetail, ProcessedFiling, Trade
from ...sec import (
    EdgarClient, EdgarError, current_feed_path, daily_index_path, filing_index_url, parse_current_feed, parse_daily_index,
    parse_form4,
)

FEED_PAGE_SIZE = 100
MAX_FEED_PAGES = 20
# Each 10-minute run reads back this far in the feed; the nightly index check covers anything older.
FEED_LOOKBACK = timedelta(hours=1)
PROCESSED_RETENTION_DAYS = 30


@dataclass
class InsiderResult:
    filings: int = 0
    trades: list[Trade] = field(default_factory=list)
    unpublished_days: list[date] = field(default_factory=list)
    # Set when SEC stopped answering part-way; everything stored before that is kept.
    error: str | None = None


def _processed(db: Session, accessions: list[str]) -> set[str]:
    if not accessions:
        return set()
    return set(db.scalars(select(ProcessedFiling.accession_no).where(ProcessedFiling.accession_no.in_(accessions))))


def _already_reported(db: Session, company_id: int, parsed) -> bool:
    """Funds and their partners often each file a Form 4 for the same shares; keep the first one only."""
    candidates = db.scalars(
        select(InsiderTradeDetail).join(Trade).where(
            Trade.source == SOURCE_FORM4, Trade.company_id == company_id, Trade.trade_date == parsed.trade_date,
            Trade.direction == (BUY if parsed.code == "P" else SELL), InsiderTradeDetail.shares == parsed.shares,
        )
    )
    return any(
        (d.avg_price is None and parsed.avg_price is None)
        or (d.avg_price is not None and parsed.avg_price is not None and abs(d.avg_price - parsed.avg_price) < 0.005)
        for d in candidates
    )


def store_filing(
    db: Session, edgar: EdgarClient, accession_no: str, filer_cik: int, filed: date, companies: dict[int, Company],
) -> list[Trade] | None:
    """Read one Form 4 and store its open-market buys and sells. None if SEC doesn't have it yet."""
    submission = edgar.get_text(f"/Archives/edgar/data/{filer_cik}/{accession_no}.txt")
    if submission is None:
        return None
    trades = []
    for parsed in parse_form4(submission, accession_no):
        company = companies.get(parsed.issuer_cik)
        if company is None or _already_reported(db, company.id, parsed):
            continue
        trade = Trade(
            source=SOURCE_FORM4,
            external_id=f"{accession_no}:{parsed.code}",
            company_id=company.id,
            ticker=company.ticker,
            asset_name=company.name,
            actor_name=parsed.insider_name,
            actor_role=parsed.insider_title,
            direction=BUY if parsed.code == "P" else SELL,
            value_low=parsed.value,
            value_high=parsed.value,
            trade_date=parsed.trade_date,
            filed_date=filed,
            source_url=filing_index_url(parsed.issuer_cik, accession_no),
            tags=[],
        )
        trade.insider = InsiderTradeDetail(
            accession_no=accession_no, transaction_code=parsed.code, shares=parsed.shares,
            avg_price=parsed.avg_price, shares_owned_after=parsed.shares_owned_after, is_10b5_1=parsed.is_10b5_1,
        )
        db.add(trade)
        trades.append(trade)
    db.add(ProcessedFiling(accession_no=accession_no, filed_date=filed, trades=len(trades)))
    db.commit()
    return trades


def ingest_live_feed(db: Session, edgar: EdgarClient, companies: dict[int, Company]) -> InsiderResult:
    """New Form 4s from SEC's live feed, newest first, until we reach ones already read."""
    result = InsiderResult()
    try:
        _read_feed(db, edgar, companies, result)
    except EdgarError as exc:
        db.rollback()
        result.error = str(exc)
    return result


def _read_feed(db: Session, edgar: EdgarClient, companies: dict[int, Company], result: InsiderResult) -> None:
    candidates: dict[str, int] = {}
    filed_on: dict[str, date] = {}
    newest = None
    for page in range(MAX_FEED_PAGES):
        entries = parse_current_feed(edgar.get_text(current_feed_path(page * FEED_PAGE_SIZE, FEED_PAGE_SIZE)) or "<feed/>")
        if not entries:
            break
        newest = newest or entries[0].updated
        forms = [e for e in entries if e.form == "4"]
        already = _processed(db, [e.accession_no for e in forms])
        for e in forms:
            # Each filing appears once for the company ("Issuer") and once per insider; keep the company entry.
            if e.role == "Issuer" and e.cik in companies and e.accession_no not in already:
                candidates.setdefault(e.accession_no, e.cik)
                filed_on[e.accession_no] = e.filed
        if already or entries[-1].updated < newest - FEED_LOOKBACK:
            break

    for accession_no, cik in candidates.items():
        trades = store_filing(db, edgar, accession_no, cik, filed_on[accession_no], companies)
        if trades is not None:
            result.filings += 1
            result.trades.extend(trades)


def recent_business_days(today: date, count: int) -> list[date]:
    days, day = [], today
    while len(days) < count:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return sorted(days)


def reconcile_days(db: Session, edgar: EdgarClient, companies: dict[int, Company], days: list[date]) -> InsiderResult:
    """Catch anything the live feed missed, from SEC's end-of-day index (published each evening)."""
    result = InsiderResult()
    try:
        for day in days:
            _reconcile_day(db, edgar, companies, day, result)
    except EdgarError as exc:
        db.rollback()
        result.error = str(exc)
    return result


def _reconcile_day(db: Session, edgar: EdgarClient, companies: dict[int, Company], day: date,
                   result: InsiderResult) -> None:
    index = edgar.get_text(daily_index_path(day))
    if index is None:
        result.unpublished_days.append(day)  # holiday, or not out yet
        return
    filings = {}
    for entry in parse_daily_index(index):
        if entry.form == "4" and entry.cik in companies:
            filings.setdefault(entry.accession_no, entry)
    done = _processed(db, list(filings))
    for accession_no, entry in filings.items():
        if accession_no in done:
            continue
        trades = store_filing(db, edgar, accession_no, entry.cik, entry.filed, companies)
        if trades is not None:
            result.filings += 1
            result.trades.extend(trades)


def prune_processed(db: Session, today: date) -> int:
    cutoff = today - timedelta(days=PROCESSED_RETENTION_DAYS)
    old = db.scalars(select(ProcessedFiling).where(ProcessedFiling.filed_date < cutoff)).all()
    for row in old:
        db.delete(row)
    db.commit()
    return len(old)
