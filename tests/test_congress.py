from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.agents.scout.congress import (
    QUIVER_BASE, LIVE_CONGRESS_PATH, QuiverClient, QuiverError, ingest_congress, parse_congress_row, parse_range,
)
from app.models import Company, Politician, Trade


@pytest.mark.parametrize("label, expected", [
    ("$1,001 - $15,000", (1001, 15000)),
    ("$1,000,001 - $5,000,000", (1_000_001, 5_000_000)),
    ("Over $50,000,000", (50_000_000, None)),
    ("$15,001", (15001, 15001)),
    ("unknown", (None, None)),
])
def test_parse_range(label, expected):
    assert parse_range(label) == expected


def _row(**extra) -> dict:
    row = {"Representative": "Maria Cantwell", "BioGuideID": "C000127", "House": "Senate", "Ticker": "BRK-B",
           "Transaction": "Sale (Partial)", "Range": "$15,001 - $50,000", "TransactionDate": "2026-08-20T00:00:00",
           "ReportDate": "2026-09-26", "Owner": "Joint", "Description": "Berkshire Hathaway Class B"}
    row.update(extra)
    return row


def test_parse_congress_row():
    t = parse_congress_row(_row())
    assert (t.source, t.direction, t.ticker, t.owner) == ("senate", "sell", "BRK.B", "Joint")
    assert (t.value_low, t.value_high, t.trade_date, t.report_date) == (15001, 50000, date(2026, 8, 20), date(2026, 9, 26))
    assert parse_congress_row(_row()).external_id == t.external_id  # stable across fetches
    assert parse_congress_row(_row(Owner="Self")).external_id != t.external_id


def test_parse_congress_row_alternatives_and_skips():
    house = parse_congress_row(_row(House="Representatives", Transaction="Purchase", Range="", Amount="1001.0"))
    assert (house.source, house.direction, house.value_low, house.value_high, house.amount_range) == (
        "house", "buy", 1001, None, "$1,001+")
    assert parse_congress_row(_row(Transaction="Exchange")) is None
    assert parse_congress_row(_row(ReportDate="")) is None
    assert parse_congress_row(_row(Ticker="--")).ticker == ""


class FakeQuiver:
    def __init__(self, rows):
        self.rows = rows

    def recent_congress_trades(self):
        return self.rows


def test_ingest_congress_matches_members_and_companies(db, seeded):
    db.add(Company(ticker="BRK.B", name="Berkshire Hathaway", cik="0001067983"))
    db.commit()
    by_ticker = {c.ticker: c for c in db.scalars(select(Company))}
    politicians = db.scalars(select(Politician)).all()
    rows = [_row(), _row(BioGuideID="", Representative="Nancy Pelosi", House="Representatives", Ticker="ZZZZ",
                         Description="Some private fund"), {"junk": True}, "not a dict"]

    trades = ingest_congress(db, FakeQuiver(rows), by_ticker, politicians)
    assert len(trades) == 2
    cantwell, pelosi = trades
    assert (cantwell.politician.full_name, cantwell.company.ticker, cantwell.actor_role) == (
        "Maria Cantwell", "BRK.B", "Senator (D-WA)")
    assert cantwell.congress.amount_range == "$15,001 - $50,000"
    assert (pelosi.politician.full_name, pelosi.company_id, pelosi.asset_name) == ("Nancy Pelosi", None, "Some private fund")

    assert ingest_congress(db, FakeQuiver(rows), by_ticker, politicians) == []
    assert len(db.scalars(select(Trade)).all()) == 2


def _quiver(handler) -> QuiverClient:
    return QuiverClient("secret-key", httpx.Client(transport=httpx.MockTransport(handler)))


def test_quiver_client_sends_key_and_returns_rows():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["Authorization"]
        return httpx.Response(200, json=[_row()])

    assert _quiver(handler).recent_congress_trades() == [_row()]
    assert seen == {"url": QUIVER_BASE + LIVE_CONGRESS_PATH, "auth": "Token secret-key"}


@pytest.mark.parametrize("response, message", [
    (httpx.Response(401), "refused the API key"),
    (httpx.Response(500), "HTTP 500"),
    (httpx.Response(200, json={"error": "x"}), "wasn't a list"),
    (httpx.Response(200, text="<html>"), "isn't JSON"),
])
def test_quiver_client_errors(response, message):
    with pytest.raises(QuiverError, match=message):
        _quiver(lambda r: response).recent_congress_trades()


def test_quiver_client_needs_a_key():
    with pytest.raises(QuiverError, match="QUIVER_API_KEY"):
        QuiverClient("")
