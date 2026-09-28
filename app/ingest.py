from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SOURCE_FORM4, Company, IngestedDay, Trade
from .sec import EdgarClient, daily_index_path, filing_index_url, parse_daily_index, parse_form4

DEFAULT_LOOKBACK_DAYS = 5
# EDGAR publishes each day's index that evening; one still missing after this many business days is a holiday.
INDEX_GRACE_BUSINESS_DAYS = 2


@dataclass
class DayResult:
    day: date
    filings: int = 0
    trades: list[Trade] = field(default_factory=list)
    published: bool = True


def days_to_ingest(db: Session, today: date, lookback: int = DEFAULT_LOOKBACK_DAYS) -> list[date]:
    """Weekdays before today (today's index isn't out yet) that haven't been processed."""
    done = set(db.scalars(select(IngestedDay.day).where(IngestedDay.source == SOURCE_FORM4)))
    candidates = (today - timedelta(days=n) for n in range(lookback, 0, -1))
    return [d for d in candidates if d.weekday() < 5 and d not in done]


def business_days_between(start: date, end: date) -> int:
    return sum(1 for n in range(1, (end - start).days + 1) if (start + timedelta(days=n)).weekday() < 5)


def ingest_day(db: Session, edgar: EdgarClient, day: date, today: date) -> DayResult:
    index = edgar.get_text(daily_index_path(day))
    if index is None:
        if business_days_between(day, today) > INDEX_GRACE_BUSINESS_DAYS:
            db.add(IngestedDay(source=SOURCE_FORM4, day=day))
            db.commit()
        return DayResult(day=day, published=False)

    companies = {int(c.cik): c for c in db.scalars(select(Company).where(Company.cik.is_not(None)))}
    filings = {}
    for entry in parse_daily_index(index):
        # Each filing is listed once per party (issuer and insider); keep those involving a tracked issuer.
        if entry.form == "4" and entry.cik in companies:
            filings.setdefault(entry.accession_no, entry)

    seen = set(db.scalars(select(Trade.accession_no).where(Trade.accession_no.in_(list(filings)))))
    result = DayResult(day=day, filings=len(filings))
    for accession_no, entry in filings.items():
        if accession_no in seen:
            continue
        submission = edgar.get_text(f"/Archives/{entry.path}")
        if submission is None:
            continue
        for parsed in parse_form4(submission, accession_no):
            company = companies.get(parsed.issuer_cik)
            if company is None:
                continue
            trade = Trade(
                source=SOURCE_FORM4,
                accession_no=accession_no,
                company_id=company.id,
                ticker=company.ticker,
                insider_name=parsed.insider_name,
                insider_title=parsed.insider_title,
                code=parsed.code,
                shares=parsed.shares,
                avg_price=parsed.avg_price,
                value=parsed.value,
                shares_owned_after=parsed.shares_owned_after,
                trade_date=parsed.trade_date,
                filed_date=entry.filed,
                is_10b5_1=parsed.is_10b5_1,
                source_url=filing_index_url(parsed.issuer_cik, accession_no),
            )
            db.add(trade)
            result.trades.append(trade)

    db.add(IngestedDay(source=SOURCE_FORM4, day=day, filings=result.filings, trades=len(result.trades)))
    db.commit()
    return result
