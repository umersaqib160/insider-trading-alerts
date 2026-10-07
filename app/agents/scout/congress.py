"""Congress trades (House and Senate periodic transaction reports) from the Quiver API.

Field names follow Quiver's congress trading endpoint. Several aliases are
accepted for each field because Quiver's endpoints differ slightly; confirm
against a real response once QUIVER_API_KEY is set.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    BUY, SELL, SOURCE_HOUSE, SOURCE_SENATE, Company, CongressTradeDetail, Politician, Trade,
)
from ...refdata.listed import normalize_ticker

QUIVER_BASE = "https://api.quiverquant.com/beta"
LIVE_CONGRESS_PATH = "/live/congresstrading"
SOURCE_LINKS = {
    SOURCE_HOUSE: "https://disclosures-clerk.house.gov/FinancialDisclosure",
    SOURCE_SENATE: "https://efdsearch.senate.gov/search/",
}


class QuiverError(Exception):
    pass


class QuiverClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        if not api_key:
            raise QuiverError("QUIVER_API_KEY is not set.")
        self._http = http or httpx.Client(timeout=30)
        self._headers = {"Authorization": f"Token {api_key}", "Accept": "application/json"}

    def recent_congress_trades(self) -> list[dict]:
        try:
            response = self._http.get(QUIVER_BASE + LIVE_CONGRESS_PATH, headers=self._headers)
        except httpx.HTTPError:
            raise QuiverError("Couldn't reach the Quiver API.") from None
        if response.status_code in (401, 403):
            raise QuiverError(f"Quiver refused the API key (HTTP {response.status_code}).")
        if response.status_code != 200:
            raise QuiverError(f"Quiver returned HTTP {response.status_code}.")
        try:
            rows = response.json()
        except ValueError:
            raise QuiverError("Quiver returned something that isn't JSON.") from None
        if not isinstance(rows, list):
            raise QuiverError("Quiver's response wasn't a list of trades.")
        return rows


@dataclass(frozen=True)
class CongressTrade:
    external_id: str
    source: str
    bioguide_id: str
    name: str
    ticker: str
    description: str
    transaction_type: str
    direction: str
    amount_range: str
    value_low: float | None
    value_high: float | None
    owner: str
    trade_date: date
    report_date: date


def _field(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


_MONEY = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


def parse_range(label: str) -> tuple[float | None, float | None]:
    """'$15,001 - $50,000' -> (15001, 50000); 'Over $50,000,000' -> (50000000, None)."""
    amounts = [float(m.replace(",", "")) for m in _MONEY.findall(label)]
    if not amounts:
        return None, None
    if len(amounts) == 1:
        return amounts[0], (None if "over" in label.lower() else amounts[0])
    return amounts[0], amounts[1]


def _money_label(value: float) -> str:
    return f"${value:,.0f}"


def parse_congress_row(row: dict) -> CongressTrade | None:
    """None for rows that aren't a purchase or sale (e.g. exchanges) or lack the essentials."""
    transaction = _field(row, "Transaction", "TransactionType", "Type")
    kind = transaction.lower()
    direction = BUY if kind.startswith("purchase") else SELL if kind.startswith("sale") else None
    trade_date = _date(_field(row, "TransactionDate", "Traded", "Date"))
    report_date = _date(_field(row, "ReportDate", "Filed", "Disclosed", "DisclosureDate"))
    name = _field(row, "Representative", "Name", "Senator", "Politician")
    chamber_raw = _field(row, "House", "Chamber").lower()
    if not direction or not trade_date or not report_date or not name:
        return None
    source = SOURCE_SENATE if chamber_raw.startswith("sen") else SOURCE_HOUSE

    amount_range = _field(row, "Range", "AmountRange")
    low, high = parse_range(amount_range) if amount_range else (None, None)
    if low is None:
        amount = _field(row, "Amount")
        try:
            low = float(amount) if amount else None  # Quiver's Amount is the bottom of the range
        except ValueError:
            low = None
        amount_range = f"{_money_label(low)}+" if low else ""

    bioguide_id = _field(row, "BioGuideID", "BioguideID", "bioguide_id")
    ticker = normalize_ticker(_field(row, "Ticker")) if _field(row, "Ticker") not in ("", "-", "--") else ""
    description = _field(row, "Description", "AssetDescription", "Asset")
    owner = _field(row, "Owner")
    key = "|".join([source, bioguide_id or name, ticker, description, transaction, amount_range, owner,
                    trade_date.isoformat(), report_date.isoformat()])
    return CongressTrade(
        external_id=hashlib.sha1(key.encode()).hexdigest(),
        source=source, bioguide_id=bioguide_id, name=name, ticker=ticker, description=description,
        transaction_type=transaction, direction=direction, amount_range=amount_range,
        value_low=low, value_high=high, owner=owner, trade_date=trade_date, report_date=report_date,
    )


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def ingest_congress(
    db: Session, quiver: QuiverClient, companies_by_ticker: dict[str, Company], politicians: list[Politician],
) -> list[Trade]:
    parsed = [t for t in (parse_congress_row(r) for r in quiver.recent_congress_trades() if isinstance(r, dict)) if t]
    if not parsed:
        return []
    by_bioguide = {p.bioguide_id: p for p in politicians}
    by_name = {}
    for p in politicians:
        by_name[_name_key(p.full_name)] = p
        by_name.setdefault(_name_key(f"{p.first_name} {p.last_name}"), p)

    ids = {t.external_id for t in parsed}
    existing = set(db.scalars(select(Trade.external_id).where(
        Trade.source.in_([SOURCE_HOUSE, SOURCE_SENATE]), Trade.external_id.in_(ids))))
    trades = []
    for t in parsed:
        if t.external_id in existing:
            continue
        existing.add(t.external_id)
        politician = by_bioguide.get(t.bioguide_id) or by_name.get(_name_key(t.name))
        company = companies_by_ticker.get(t.ticker) if t.ticker else None
        role = ""
        if politician:
            role = f"{politician.role_label} ({politician.short_label})"
        trade = Trade(
            source=t.source,
            external_id=t.external_id,
            company_id=company.id if company else None,
            politician_id=politician.id if politician else None,
            ticker=t.ticker,
            asset_name=company.name if company else (t.description or t.ticker),
            actor_name=politician.full_name if politician else t.name,
            actor_role=role,
            direction=t.direction,
            value_low=t.value_low,
            value_high=t.value_high,
            trade_date=t.trade_date,
            filed_date=t.report_date,
            source_url=SOURCE_LINKS[t.source],
            tags=[],
        )
        trade.congress = CongressTradeDetail(
            chamber=t.source, owner=t.owner, amount_range=t.amount_range,
            transaction_type=t.transaction_type, description=t.description[:512],
        )
        db.add(trade)
        trades.append(trade)
    db.commit()
    return trades
