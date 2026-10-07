from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Company, Politician, utcnow
from ..sec import EdgarClient, EdgarError
from .congress import COMMITTEES_URL, LEGISLATORS_URL, MEMBERSHIP_URL, PoliticianRecord, parse_legislators
from .listed import LISTED_URL, SUBMISSIONS_URL, ListedCompany, parse_listed, parse_sic
from .sectors import sector_for_sic, tidy_industry
from .sp500 import SP500_URL, CompanyRecord, parse_constituents

# A truncated or broken download must not mark a whole list as removed.
MIN_LISTED_COMPANIES = 4000
MIN_SP500 = 450
MIN_POLITICIANS = 500
INDUSTRY_REFRESH_DAYS = 90


class ReferenceDataError(Exception):
    pass


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0

    def __str__(self) -> str:
        return f"{self.added} added, {self.updated} updated, {self.removed} removed"


def _apply(obj, values: dict) -> bool:
    changed = {k: v for k, v in values.items() if getattr(obj, k) != v}
    for k, v in changed.items():
        setattr(obj, k, v)
    return bool(changed)


def sync_listed(db: Session, records: list[ListedCompany]) -> SyncResult:
    result = SyncResult()
    existing = db.scalars(select(Company)).all()
    incoming_ciks = {r.cik for r in records}
    incoming_tickers = {r.ticker for r in records}

    # A ticker can move to a different company (e.g. after a delisting). Free it from the old holder first.
    for company in existing:
        if company.cik not in incoming_ciks and company.ticker in incoming_tickers:
            company.ticker = f"{company.ticker}~{company.id}"[:16]
            company.listed = False
    db.flush()

    by_cik = {c.cik: c for c in existing if c.cik}
    by_ticker = {c.ticker: c for c in existing}
    seen: set[int] = set()
    for r in records:
        company = by_cik.get(r.cik) or by_ticker.get(r.ticker)
        if company is None:
            company = Company(ticker=r.ticker, cik=r.cik, name=r.name, exchange=r.exchange,
                              other_tickers=list(r.other_tickers), listed=True)
            db.add(company)
            by_cik[r.cik] = by_ticker[r.ticker] = company
            result.added += 1
        else:
            values = {"cik": r.cik, "exchange": r.exchange, "other_tickers": list(r.other_tickers), "listed": True}
            if not company.in_sp500:  # S&P members keep their cleaner S&P names
                values["name"] = r.name
            if company.ticker != r.ticker and by_ticker.get(r.ticker) in (None, company):
                by_ticker.pop(company.ticker, None)
                by_ticker[r.ticker] = company
                values["ticker"] = r.ticker
            if _apply(company, values):
                result.updated += 1
        seen.add(id(company))

    for company in existing:
        if id(company) not in seen and company.listed:
            company.listed = False
            result.removed += 1
    db.commit()
    return result


def sync_sp500(db: Session, records: list[CompanyRecord]) -> SyncResult:
    """Flag S&P 500 members and give them their official GICS sector and industry."""
    result = SyncResult()
    existing = db.scalars(select(Company)).all()
    by_cik = {c.cik: c for c in existing if c.cik}
    by_ticker = {c.ticker: c for c in existing}
    members: set[int] = set()
    for r in records:
        company = (by_cik.get(r.cik) if r.cik else None) or by_ticker.get(r.ticker)
        if company is None:
            company = Company(ticker=r.ticker, cik=r.cik, name=r.name, listed=True)
            db.add(company)
            by_ticker[r.ticker] = company
            result.added += 1
        if _apply(company, {"in_sp500": True, "name": r.name, "sector": r.sector, "industry": r.sub_industry}):
            result.updated += 1
        members.add(id(company))
    for company in existing:
        if company.in_sp500 and id(company) not in members:
            company.in_sp500 = False
            company.industry_checked_at = None  # re-derive sector and industry from its SIC code
            result.removed += 1
    db.commit()
    return result


def sync_politicians(db: Session, records: list[PoliticianRecord]) -> SyncResult:
    result = SyncResult()
    existing = {p.bioguide_id: p for p in db.scalars(select(Politician))}
    for r in records:
        values = {
            "full_name": r.full_name, "first_name": r.first_name, "last_name": r.last_name,
            "chamber": r.chamber, "party": r.party, "state": r.state, "district": r.district,
            "committees": list(r.committees), "led_committees": list(r.led_committees), "active": True,
        }
        politician = existing.get(r.bioguide_id)
        if politician is None:
            db.add(Politician(bioguide_id=r.bioguide_id, **values))
            result.added += 1
        elif _apply(politician, values):
            result.updated += 1
    current = {r.bioguide_id for r in records}
    for bioguide_id, politician in existing.items():
        if bioguide_id not in current and politician.active:
            politician.active = False
            result.removed += 1
    db.commit()
    return result


def fill_industries(db: Session, edgar: EdgarClient, limit: int) -> int:
    """Look up SIC industry codes for companies that haven't been checked recently (one SEC request each)."""
    stale = utcnow() - timedelta(days=INDUSTRY_REFRESH_DAYS)
    companies = db.scalars(
        select(Company)
        .where(Company.listed.is_(True), Company.cik.is_not(None),
               or_(Company.industry_checked_at.is_(None), Company.industry_checked_at < stale))
        .order_by(Company.industry_checked_at.is_not(None), Company.industry_checked_at, Company.id)
        .limit(limit)
    ).all()
    for n, company in enumerate(companies, 1):
        payload = edgar.get_json(SUBMISSIONS_URL.format(cik=company.cik))
        if payload:
            sic, description = parse_sic(payload)
            company.sic_code = sic
            if not company.in_sp500:
                company.industry = tidy_industry(description)
                company.sector = sector_for_sic(sic)
        company.industry_checked_at = utcnow()
        if n % 100 == 0:
            db.commit()
    db.commit()
    return len(companies)


def _get(http: httpx.Client, url: str) -> httpx.Response:
    try:
        response = http.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ReferenceDataError(f"Couldn't download {url}: {exc}") from exc
    return response


def load_reference_data(db: Session, edgar: EdgarClient, http: httpx.Client | None = None) -> dict[str, SyncResult]:
    http = http or httpx.Client(timeout=60, follow_redirects=True)

    try:
        listed = parse_listed(edgar.get_json(LISTED_URL) or {"fields": [], "data": []})
    except EdgarError as exc:
        raise ReferenceDataError(str(exc)) from exc
    if len(listed) < MIN_LISTED_COMPANIES:
        raise ReferenceDataError(f"SEC's listed-company file has only {len(listed)} companies; refusing to sync.")

    sp500 = parse_constituents(_get(http, SP500_URL).text)
    if len(sp500) < MIN_SP500:
        raise ReferenceDataError(f"S&P 500 list has only {len(sp500)} companies; refusing to sync.")

    politicians = parse_legislators(
        _get(http, LEGISLATORS_URL).json(),
        _get(http, COMMITTEES_URL).json(),
        _get(http, MEMBERSHIP_URL).json(),
    )
    if len(politicians) < MIN_POLITICIANS:
        raise ReferenceDataError(f"Congress list has only {len(politicians)} members; refusing to sync.")

    return {
        "listed companies": sync_listed(db, listed),
        "S&P 500": sync_sp500(db, sp500),
        "politicians": sync_politicians(db, politicians),
    }
