from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Politician
from .congress import COMMITTEES_URL, LEGISLATORS_URL, MEMBERSHIP_URL, PoliticianRecord, parse_legislators
from .sp500 import SP500_URL, CompanyRecord, parse_constituents

# A truncated or broken download must not mark the whole index as removed.
MIN_COMPANIES = 450
MIN_POLITICIANS = 500


class ReferenceDataError(Exception):
    pass


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0

    def __str__(self) -> str:
        return f"{self.added} added, {self.updated} updated, {self.removed} removed"


def sync_companies(db: Session, records: list[CompanyRecord]) -> SyncResult:
    result = SyncResult()
    existing = {c.ticker: c for c in db.scalars(select(Company))}
    for r in records:
        company = existing.get(r.ticker)
        if company is None:
            db.add(Company(ticker=r.ticker, name=r.name, sector=r.sector, sub_industry=r.sub_industry, cik=r.cik, in_sp500=True))
            result.added += 1
            continue
        values = {"name": r.name, "sector": r.sector, "sub_industry": r.sub_industry, "cik": r.cik, "in_sp500": True}
        if any(getattr(company, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(company, k, v)
            result.updated += 1
    listed = {r.ticker for r in records}
    for ticker, company in existing.items():
        if ticker not in listed and company.in_sp500:
            # Kept rather than deleted so users' stars on it survive.
            company.in_sp500 = False
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
            "committees": list(r.committees), "active": True,
        }
        politician = existing.get(r.bioguide_id)
        if politician is None:
            db.add(Politician(bioguide_id=r.bioguide_id, **values))
            result.added += 1
        elif any(getattr(politician, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(politician, k, v)
            result.updated += 1
    current = {r.bioguide_id for r in records}
    for bioguide_id, politician in existing.items():
        if bioguide_id not in current and politician.active:
            politician.active = False
            result.removed += 1
    db.commit()
    return result


def _get(http: httpx.Client, url: str) -> httpx.Response:
    try:
        response = http.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ReferenceDataError(f"Couldn't download {url}: {exc}") from exc
    return response


def load_reference_data(db: Session, http: httpx.Client | None = None) -> dict[str, SyncResult]:
    http = http or httpx.Client(timeout=60, follow_redirects=True)

    companies = parse_constituents(_get(http, SP500_URL).text)
    if len(companies) < MIN_COMPANIES:
        raise ReferenceDataError(f"S&P 500 list has only {len(companies)} companies; refusing to sync.")

    politicians = parse_legislators(
        _get(http, LEGISLATORS_URL).json(),
        _get(http, COMMITTEES_URL).json(),
        _get(http, MEMBERSHIP_URL).json(),
    )
    if len(politicians) < MIN_POLITICIANS:
        raise ReferenceDataError(f"Congress list has only {len(politicians)} members; refusing to sync.")

    return {"companies": sync_companies(db, companies), "politicians": sync_politicians(db, politicians)}
