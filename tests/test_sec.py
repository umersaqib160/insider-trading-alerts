from datetime import date

import httpx
import pytest

from app.sec import (
    EdgarClient, EdgarError, daily_index_path, filing_index_url, parse_daily_index, parse_form4, person_name,
)

from .conftest import FIXTURES
from .form4 import APPLE_CEO_SALE, APPLE_GRANT_ONLY, NVIDIA_DIRECTOR_BUY, owner, submission, transaction


def test_daily_index_path_uses_calendar_quarter():
    assert daily_index_path(date(2026, 9, 25)) == "/Archives/edgar/daily-index/2026/QTR3/form.20260925.idx"
    assert daily_index_path(date(2026, 10, 1)) == "/Archives/edgar/daily-index/2026/QTR4/form.20261001.idx"


def test_filing_index_url():
    assert filing_index_url(320193, "0001140361-26-000101") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000114036126000101/0001140361-26-000101-index.htm"
    )


def test_parse_daily_index():
    entries = parse_daily_index((FIXTURES / "form_index_sample.idx").read_text())
    assert len(entries) == 8
    first = entries[0]
    assert (first.form, first.company, first.cik) == ("1-A POS", "Modern Mining Technology Corp.", 1898722)
    apple = entries[1]
    assert (apple.form, apple.cik, apple.filed, apple.accession_no) == ("4", 320193, date(2026, 9, 25), "0001140361-26-000101")
    assert [e.form for e in entries].count("4/A") == 1


def test_parse_form4_totals_sales_and_skips_other_codes():
    [trade] = parse_form4(APPLE_CEO_SALE, "0001140361-26-000101")
    assert (trade.code, trade.ticker, trade.issuer_cik) == ("S", "AAPL", 320193)
    assert trade.insider_name == "Timothy D Cook"
    assert trade.insider_title == "Chief Executive Officer"
    assert trade.shares == 4000
    assert trade.avg_price == pytest.approx(251.5)  # (1000*250 + 3000*252) / 4000
    assert trade.value == pytest.approx(1_006_000)
    assert trade.trade_date == date(2026, 9, 23)
    assert trade.shares_owned_after == 6000
    assert trade.is_10b5_1 is True


def test_parse_form4_purchase_by_director():
    [trade] = parse_form4(NVIDIA_DIRECTOR_BUY, "0001045810-26-000202")
    assert (trade.code, trade.insider_title, trade.shares, trade.value) == ("P", "Director", 2000, 361_000)
    assert trade.is_10b5_1 is False


def test_parse_form4_ignores_grants_and_amendments():
    assert parse_form4(APPLE_GRANT_ONLY, "x") == []
    amendment = submission("x", [transaction("S", "10", "1", "2026-09-24")], [owner("A")], document_type="4/A")
    assert parse_form4(amendment, "x") == []


def test_parse_form4_mixed_buy_and_sell_produce_one_trade_each():
    text = submission("x", [
        transaction("P", "100", "10", "2026-09-22"),
        transaction("S", "40", "12", "2026-09-23"),
    ], [owner("A", director=True)])
    assert sorted(t.code for t in parse_form4(text, "x")) == ["P", "S"]


def test_parse_form4_multiple_owners_and_roles():
    text = submission("x", [transaction("P", "5", "1", "2026-09-24")], [
        owner("Big Fund LP", ten_percent=True, director=True), owner("Big Fund GP LLC"), owner("Jane Partner"),
    ])
    [trade] = parse_form4(text, "x")
    assert trade.insider_name == "Big Fund LP and 2 others"
    assert trade.insider_title == "Director, 10% Owner"


def test_parse_form4_without_price_keeps_shares():
    text = submission("x", [transaction("S", "300", None, "2026-09-24")], [owner("A", director=True)])
    [trade] = parse_form4(text, "x")
    assert (trade.shares, trade.avg_price, trade.value) == (300, None, None)


@pytest.mark.parametrize("raw, shown", [
    ("SAMUELI HENRY", "Henry Samueli"),
    ("Teter Timothy S.", "Timothy S. Teter"),
    ("Le-Quoc Alexis", "Alexis Le-Quoc"),
    ("SMITH JOHN A JR", "John A Smith Jr"),
    ("BERKSHIRE HATHAWAY INC", "Berkshire Hathaway Inc"),
    ("Big Fund LP", "Big Fund LP"),
    ("Madonna", "Madonna"),
])
def test_person_name(raw, shown):
    assert person_name(raw) == shown


def test_officer_titles_in_capitals_are_tidied():
    text = submission("x", [transaction("S", "1", "1", "2026-09-24")], [owner("A B", officer_title="PRESIDENT AND CEO")])
    assert parse_form4(text, "x")[0].insider_title == "President and CEO"


def test_parse_form4_tolerates_garbage():
    assert parse_form4("no xml here", "x") == []
    assert parse_form4("<XML><ownershipDocument><unclosed></XML>", "x") == []


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _edgar(handler, clock=None) -> EdgarClient:
    clock = clock or FakeClock()
    return EdgarClient("Behind The Curtain test@example.com", httpx.Client(transport=httpx.MockTransport(handler)),
                       sleep=clock.sleep, clock=clock)


def test_edgar_client_sends_user_agent_and_throttles():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, text="ok")

    clock = FakeClock()
    client = _edgar(handler, clock)
    assert client.get_text("/a") == "ok"
    assert client.get_text("/b") == "ok"
    assert seen == ["Behind The Curtain test@example.com"] * 2
    assert clock.slept == [pytest.approx(0.15)]


def test_edgar_client_404_is_none_and_errors_raise():
    assert _edgar(lambda r: httpx.Response(404)).get_text("/missing") is None
    with pytest.raises(EdgarError, match="HTTP 503"):
        _edgar(lambda r: httpx.Response(503)).get_text("/busy")


def test_edgar_client_requires_user_agent():
    with pytest.raises(EdgarError, match="SEC_USER_AGENT"):
        EdgarClient("")
