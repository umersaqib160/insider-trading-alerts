import json

import httpx
import pytest
from sqlalchemy import select

from app.models import Company, CompanyWatch, Politician, User
from app.refdata import load as load_module
from app.refdata.congress import (
    COMMITTEES_URL, LEGISLATORS_URL, MEMBERSHIP_URL, committee_short_name, parse_legislators,
)
from app.refdata.load import ReferenceDataError, load_reference_data, sync_companies, sync_politicians
from app.refdata.sp500 import SP500_URL, CompanyRecord, parse_constituents

from .conftest import FIXTURES


def _json(name: str):
    return json.loads((FIXTURES / name).read_text())


def _legislators():
    return parse_legislators(_json("legislators_sample.json"), _json("committees_sample.json"), _json("membership_sample.json"))


def test_parse_constituents():
    records = {r.ticker: r for r in parse_constituents((FIXTURES / "constituents_sample.csv").read_text())}
    assert sorted(records) == ["AAPL", "BRK.B", "NVDA", "XYZ"]
    assert records["AAPL"] == CompanyRecord("AAPL", "Apple Inc.", "Information Technology",
                                            "Technology Hardware, Storage & Peripherals", "0000320193")
    assert records["XYZ"].cik is None


@pytest.mark.parametrize("name, short", [
    ("House Committee on Agriculture", "Agriculture"),
    ("Senate Committee on the Budget", "Budget"),
    ("House Permanent Select Committee on Intelligence", "Intelligence"),
    ("Senate Special Committee on Aging", "Aging"),
    ("Joint Committee on Taxation", "Taxation"),
    ("Joint Economic Committee", "Joint Economic Committee"),
    ("Commission on Security and Cooperation in Europe", "Commission on Security and Cooperation in Europe"),
])
def test_committee_short_name(name, short):
    assert committee_short_name(name) == short


def test_parse_legislators():
    people = {p.bioguide_id: p for p in _legislators()}
    assert sorted(people) == ["B001236", "C000127", "S000033", "Z000017"]

    cantwell = people["C000127"]
    assert (cantwell.chamber, cantwell.party, cantwell.state, cantwell.district) == ("senate", "D", "WA", None)
    assert cantwell.committees == ["Agriculture, Nutrition, and Forestry", "Intelligence"]

    assert people["B001236"].committees == ["Agriculture, Nutrition, and Forestry"]
    assert people["S000033"].party == "I"

    zeldin = people["Z000017"]
    assert (zeldin.full_name, zeldin.chamber, zeldin.district) == ("Lee Zeldin", "house", 0)
    assert zeldin.committees == ["Joint Economic Committee"]


def test_sync_companies_adds_updates_and_retires(db):
    records = parse_constituents((FIXTURES / "constituents_sample.csv").read_text())
    assert (r := sync_companies(db, records)).added == 4 and r.updated == 0 and r.removed == 0

    user = User(telegram_id=1, first_name="U")
    db.add(user)
    db.commit()
    nvda = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    db.add(CompanyWatch(user_id=user.id, company_id=nvda.id))
    db.commit()

    renamed = [CompanyRecord(r.ticker, "Apple", r.sector, r.sub_industry, r.cik) if r.ticker == "AAPL" else r
               for r in records if r.ticker != "NVDA"]
    result = sync_companies(db, renamed)
    assert (result.added, result.updated, result.removed) == (0, 1, 1)
    db.refresh(nvda)
    assert nvda.in_sp500 is False
    assert db.get(CompanyWatch, (user.id, nvda.id)) is not None

    assert str(sync_companies(db, renamed)) == "0 added, 0 updated, 0 removed"


def test_sync_politicians_retires_and_restores_members(db):
    people = _legislators()
    assert sync_politicians(db, people).added == 4
    result = sync_politicians(db, [p for p in people if p.bioguide_id != "S000033"])
    assert result.removed == 1
    assert db.scalar(select(Politician.active).where(Politician.bioguide_id == "S000033")) is False
    assert sync_politicians(db, people).updated == 1
    assert db.scalar(select(Politician.active).where(Politician.bioguide_id == "S000033")) is True


def _transport(overrides: dict | None = None) -> httpx.Client:
    routes = {
        SP500_URL: (FIXTURES / "constituents_sample.csv").read_text(),
        LEGISLATORS_URL: (FIXTURES / "legislators_sample.json").read_text(),
        COMMITTEES_URL: (FIXTURES / "committees_sample.json").read_text(),
        MEMBERSHIP_URL: (FIXTURES / "membership_sample.json").read_text(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if overrides and url in overrides:
            return overrides[url]
        return httpx.Response(200, text=routes[url])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_load_reference_data(db, monkeypatch):
    monkeypatch.setattr(load_module, "MIN_COMPANIES", 1)
    monkeypatch.setattr(load_module, "MIN_POLITICIANS", 1)
    results = load_reference_data(db, _transport())
    assert results["companies"].added == 4
    assert results["politicians"].added == 4


def test_load_refuses_suspiciously_short_lists(db):
    with pytest.raises(ReferenceDataError, match="only 4 companies"):
        load_reference_data(db, _transport())
    assert db.scalar(select(Company)) is None


def test_load_reports_download_failures(db):
    client = _transport({SP500_URL: httpx.Response(503)})
    with pytest.raises(ReferenceDataError, match="Couldn't download"):
        load_reference_data(db, client)
