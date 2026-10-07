import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import Company, CompanyWatch, Politician, User, utcnow
from app.refdata import load as load_module
from app.refdata.congress import (
    COMMITTEES_URL, LEGISLATORS_URL, MEMBERSHIP_URL, committee_short_name, parse_legislators,
)
from app.refdata.listed import LISTED_URL, SUBMISSIONS_URL, ListedCompany, normalize_ticker, parse_listed
from app.refdata.load import (
    ReferenceDataError, fill_industries, load_reference_data, sync_listed, sync_politicians, sync_sp500,
)
from app.refdata.sectors import sector_for_sic, tidy_industry
from app.refdata.sp500 import SP500_URL, CompanyRecord, parse_constituents

from .conftest import FIXTURES


def _json(name: str):
    return json.loads((FIXTURES / name).read_text())


def _legislators():
    return parse_legislators(_json("legislators_sample.json"), _json("committees_sample.json"), _json("membership_sample.json"))


class FakeEdgar:
    def __init__(self, json_by_url: dict):
        self.json_by_url = json_by_url
        self.requested: list[str] = []

    def get_json(self, path: str):
        self.requested.append(path)
        return self.json_by_url.get(path)


# ---------- parsing ----------

def test_parse_listed_keeps_one_row_per_company_and_skips_otc():
    companies = {c.ticker: c for c in parse_listed(_json("listed_sample.json"))}
    assert sorted(companies) == ["AAPL", "BRK.B", "GOOGL", "NVDA", "SCBO"]
    assert companies["BRK.B"].other_tickers == ["BRK.A"]
    assert companies["GOOGL"].other_tickers == ["GOOG"]
    assert companies["AAPL"].cik == "0000320193"
    assert companies["SCBO"].exchange == "CBOE"


def test_normalize_ticker():
    assert normalize_ticker(" brk-b ") == "BRK.B"


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
])
def test_committee_short_name(name, short):
    assert committee_short_name(name) == short


def test_parse_legislators():
    people = {p.bioguide_id: p for p in _legislators()}
    assert sorted(people) == ["B001236", "C000127", "S000033", "Z000017"]
    cantwell = people["C000127"]
    assert (cantwell.chamber, cantwell.party, cantwell.state, cantwell.district) == ("senate", "D", "WA", None)
    assert cantwell.committees == ["Agriculture, Nutrition, and Forestry", "Intelligence"]
    assert people["B001236"].led_committees == ["Agriculture, Nutrition, and Forestry"]  # "Chairman"
    assert cantwell.led_committees == []
    assert people["S000033"].party == "I"
    assert (people["Z000017"].full_name, people["Z000017"].district) == ("Lee Zeldin", 0)


@pytest.mark.parametrize("sic, sector", [
    (3674, "Information Technology"), (2834, "Health Care"), (1311, "Energy"), (3812, "Industrials"),
    (6022, "Financials"), (6798, "Real Estate"), (7372, "Information Technology"), (4911, "Utilities"),
    (3711, "Consumer Discretionary"), (None, ""), (9999, ""),
])
def test_sector_for_sic(sic, sector):
    assert sector_for_sic(sic) == sector


def test_tidy_industry():
    assert tidy_industry("SERVICES-PREPACKAGED SOFTWARE") == "Services-Prepackaged Software"
    assert tidy_industry("Semiconductors & Related Devices") == "Semiconductors & Related Devices"


# ---------- syncing ----------

def _listed():
    return parse_listed(_json("listed_sample.json"))


def test_sync_listed_adds_updates_and_delists(db):
    assert sync_listed(db, _listed()).added == 5

    user = User(telegram_id=1, first_name="U")
    db.add(user)
    db.commit()
    nvda = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    db.add(CompanyWatch(user_id=user.id, company_id=nvda.id))
    db.commit()

    renamed = [ListedCompany(c.cik, "Apple", c.ticker, c.exchange, c.other_tickers) if c.ticker == "AAPL" else c
               for c in _listed() if c.ticker != "NVDA"]
    result = sync_listed(db, renamed)
    assert (result.added, result.updated, result.removed) == (0, 1, 1)
    db.refresh(nvda)
    assert nvda.listed is False
    assert db.get(CompanyWatch, (user.id, nvda.id)) is not None  # stars survive
    assert str(sync_listed(db, renamed)) == "0 added, 0 updated, 0 removed"


def test_sync_listed_follows_ticker_changes_and_reused_tickers(db):
    sync_listed(db, _listed())
    moved = [ListedCompany("0000320193", "Apple Inc.", "APPL2", "Nasdaq"),
             ListedCompany("0009999999", "New Owner Of NVDA", "NVDA", "NYSE")]
    sync_listed(db, moved)
    assert db.scalar(select(Company.ticker).where(Company.cik == "0000320193")) == "APPL2"
    new = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    assert new.cik == "0009999999" and new.listed
    old = db.scalar(select(Company).where(Company.cik == "0001045810"))
    assert old.listed is False and old.ticker.startswith("NVDA~")


def test_sync_sp500_flags_members_and_keeps_names(db):
    sync_listed(db, _listed())
    sp500 = parse_constituents((FIXTURES / "constituents_sample.csv").read_text())
    result = sync_sp500(db, sp500)
    assert result.added == 1  # XYZ isn't in the listed sample
    apple = db.scalar(select(Company).where(Company.ticker == "AAPL"))
    assert apple.in_sp500 and apple.sector == "Information Technology"
    assert db.scalar(select(Company.name).where(Company.ticker == "BRK.B")) == "Berkshire Hathaway"
    assert db.scalar(select(Company.in_sp500).where(Company.ticker == "GOOGL")) is False

    sync_listed(db, _listed())  # the nightly listed sync must not overwrite the S&P name
    assert db.scalar(select(Company.name).where(Company.ticker == "BRK.B")) == "Berkshire Hathaway"

    assert sync_sp500(db, [r for r in sp500 if r.ticker != "NVDA"]).removed == 1
    nvda = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    assert nvda.in_sp500 is False and nvda.industry_checked_at is None


def test_sync_politicians_retires_and_restores_members(db):
    people = _legislators()
    assert sync_politicians(db, people).added == 4
    assert db.scalar(select(Politician.led_committees).where(Politician.bioguide_id == "B001236")) == [
        "Agriculture, Nutrition, and Forestry"]
    assert sync_politicians(db, [p for p in people if p.bioguide_id != "S000033"]).removed == 1
    assert db.scalar(select(Politician.active).where(Politician.bioguide_id == "S000033")) is False
    assert sync_politicians(db, people).updated == 1


def test_fill_industries_uses_sic_except_for_sp500(db):
    sync_listed(db, _listed())
    apple = db.scalar(select(Company).where(Company.ticker == "AAPL"))
    apple.in_sp500, apple.sector, apple.industry = True, "Information Technology", "Technology Hardware"
    db.commit()
    edgar = FakeEdgar({
        SUBMISSIONS_URL.format(cik="0001045810"): {"sic": "3674", "sicDescription": "SEMICONDUCTORS & RELATED DEVICES"},
        SUBMISSIONS_URL.format(cik="0000320193"): {"sic": "3571", "sicDescription": "Electronic Computers"},
    })
    assert fill_industries(db, edgar, limit=10) == 5
    nvda = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    assert (nvda.sic_code, nvda.sector, nvda.industry) == (3674, "Information Technology", "Semiconductors & Related Devices")
    db.refresh(apple)
    assert (apple.sic_code, apple.industry) == (3571, "Technology Hardware")  # GICS wins for S&P members

    assert fill_industries(db, edgar, limit=10) == 0  # checked recently
    nvda.industry_checked_at = utcnow() - timedelta(days=100)
    db.commit()
    assert fill_industries(db, edgar, limit=10) == 1


# ---------- full load ----------

def _http(overrides: dict | None = None) -> httpx.Client:
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


def _relax_minimums(monkeypatch):
    for name in ("MIN_LISTED_COMPANIES", "MIN_SP500", "MIN_POLITICIANS"):
        monkeypatch.setattr(load_module, name, 1)


def test_load_reference_data(db, monkeypatch):
    _relax_minimums(monkeypatch)
    results = load_reference_data(db, FakeEdgar({LISTED_URL: _json("listed_sample.json")}), _http())
    assert results["listed companies"].added == 5
    assert results["politicians"].added == 4
    assert db.scalar(select(Company.in_sp500).where(Company.ticker == "AAPL")) is True


def test_load_refuses_suspiciously_short_lists(db):
    with pytest.raises(ReferenceDataError, match="only 5 companies"):
        load_reference_data(db, FakeEdgar({LISTED_URL: _json("listed_sample.json")}), _http())
    assert db.scalar(select(Company)) is None


def test_load_reports_download_failures(db, monkeypatch):
    _relax_minimums(monkeypatch)
    with pytest.raises(ReferenceDataError, match="Couldn't download"):
        load_reference_data(db, FakeEdgar({LISTED_URL: _json("listed_sample.json")}),
                            _http({SP500_URL: httpx.Response(503)}))
