from datetime import datetime

from sqlalchemy import func, select

from app.models import Alert, CompanyWatch, PoliticianWatch, User

from .conftest import HX, login_params, toast_of
from .factories import congress_trade, insider_trade


def test_stocks_page_lists_listed_companies(logged_in, seeded):
    html = logged_in.get("/stocks").text
    assert "Apple Inc." in html and "Small Co" in html
    assert "Departed Co" not in html
    assert "5 US companies" in html


def test_sp500_filter(logged_in, seeded):
    html = logged_in.get("/stocks/rows", params={"sp500": "1"}).text
    assert "AAPL" in html and "SMCO" not in html
    assert "4 of 5 companies" in html


def test_stocks_are_paged(logged_in, seeded, monkeypatch):
    from app.routes import lists
    monkeypatch.setattr(lists, "PAGE_SIZE", 2)
    first = logged_in.get("/stocks/rows", params={"sort": "ticker"}).text
    assert ">AAPL<" in first and ">LMT<" in first and ">NVDA<" not in first
    assert "Show more (3 left)" in first
    second = logged_in.get("/stocks/rows", params={"sort": "ticker", "offset": 2}).text
    assert ">NVDA<" in second and ">SMCO<" in second and "<table" not in second
    assert "Show more (1 left)" in second


def test_stocks_page_explains_how_to_load_data(logged_in):
    assert "No companies loaded yet" in logged_in.get("/stocks").text


def test_stock_search_matches_ticker_or_name(logged_in, seeded):
    by_name = logged_in.get("/stocks/rows", params={"q": "nvid"}).text
    assert "NVDA" in by_name and "AAPL" not in by_name
    by_ticker = logged_in.get("/stocks/rows", params={"q": "aapl"}).text
    assert "AAPL" in by_ticker and "NVDA" not in by_ticker


def test_stock_search_treats_sql_wildcards_literally(logged_in, seeded):
    assert "No companies match" in logged_in.get("/stocks/rows", params={"q": "%"}).text


def test_sector_filter(logged_in, seeded):
    html = logged_in.get("/stocks/rows", params={"sector": "Energy"}).text
    assert "XOM" in html and "AAPL" not in html


def test_star_and_unstar_company(logged_in, seeded, db):
    first = logged_in.post("/watch/company/aapl", headers=HX)
    assert first.status_code == 200
    assert 'aria-pressed="true"' in first.text
    assert 'id="nav-stocks" hx-swap-oob="true">1<' in first.text
    assert toast_of(first).startswith("Starred AAPL")
    assert db.scalar(select(func.count()).select_from(CompanyWatch)) == 1

    second = logged_in.post("/watch/company/AAPL", headers=HX)
    assert 'aria-pressed="false"' in second.text
    assert toast_of(second) == "Removed AAPL from your alerts."
    assert db.scalar(select(func.count()).select_from(CompanyWatch)) == 0


def test_starred_only_filter(logged_in, seeded):
    empty = logged_in.get("/stocks/rows", params={"starred": "1"}).text
    assert "haven't starred any companies yet" in empty
    logged_in.post("/watch/company/NVDA", headers=HX)
    html = logged_in.get("/stocks/rows", params={"starred": "1"}).text
    assert "NVDA" in html and "AAPL" not in html


def test_star_unknown_company_is_404(logged_in, seeded):
    assert logged_in.post("/watch/company/NOPE", headers=HX).status_code == 404


def test_watchlists_are_per_user(make_client, seeded):
    alice, bob = make_client(), make_client()
    alice.get("/auth/telegram", params=login_params(telegram_id=1))
    bob.get("/auth/telegram", params=login_params(telegram_id=2))
    alice.post("/watch/company/AAPL", headers=HX)
    bob_page = bob.get("/stocks").text
    assert 'id="nav-stocks">0<' in bob_page
    assert 'aria-pressed="true"' not in bob_page


def test_politician_filters(logged_in, seeded):
    def names(**params):
        html = logged_in.get("/politicians/cards", params=params).text
        return {n for n in ("Maria Cantwell", "John Boozman", "Nancy Pelosi") if n in html}

    assert names() == {"Maria Cantwell", "John Boozman", "Nancy Pelosi"}
    assert names(chamber="house") == {"Nancy Pelosi"}
    assert names(party="R") == {"John Boozman"}
    assert names(state="WA") == {"Maria Cantwell"}
    assert names(q="pel") == {"Nancy Pelosi"}


def test_politician_card_shows_seat_and_committees(logged_in, seeded):
    html = logged_in.get("/politicians").text
    assert "Representative · Democrat · California, district 11" in html
    assert "Commerce, Science, and Transportation · Intelligence" in html
    assert "Congress · 3 members" in html


def test_star_politician_moves_them_to_the_top(logged_in, seeded, db):
    response = logged_in.post("/watch/politician/P000197", headers=HX)
    assert 'aria-pressed="true"' in response.text
    assert toast_of(response).startswith("Starred Rep. Nancy Pelosi")
    assert db.scalar(select(func.count()).select_from(PoliticianWatch)) == 1
    html = logged_in.get("/politicians").text
    assert html.index("Nancy Pelosi") < html.index("John Boozman")


def test_star_unknown_politician_is_404(logged_in, seeded):
    assert logged_in.post("/watch/politician/X999", headers=HX).status_code == 404


def test_alerts_page_shows_empty_state(logged_in):
    assert "No alerts yet" in logged_in.get("/alerts").text


def test_stocks_show_latest_trade_and_sort_by_recency(logged_in, seeded, db):
    insider_trade(db, "XOM", buy=False, days_ago=10)
    insider_trade(db, "NVDA", buy=True, days_ago=1)
    insider_trade(db, "NVDA", buy=False, days_ago=5)
    insider_trade(db, "AAPL", buy=True, days_ago=120)  # outside the 90-day window

    html = logged_in.get("/stocks/rows").text
    assert html.index(">NVDA<") < html.index(">XOM<") < html.index(">AAPL<")
    assert "yesterday" in html and "$1.0M" in html
    assert "1&nbsp;buy · 1&nbsp;sell" in html

    by_ticker = logged_in.get("/stocks/rows", params={"sort": "ticker"}).text
    assert by_ticker.index(">AAPL<") < by_ticker.index(">NVDA<")


def test_starred_companies_come_first(logged_in, seeded):
    logged_in.post("/watch/company/SMCO", headers=HX)
    html = logged_in.get("/stocks/rows", params={"sort": "ticker"}).text
    assert html.index(">SMCO<") < html.index(">AAPL<")


def test_company_page_lists_insider_and_congress_trades(logged_in, seeded, db):
    trade = insider_trade(db, "AAPL", buy=False, days_ago=3, plan=True, owned_after=6000)
    trade.tags = [{"label": "CEO", "points": 20, "public": True}, {"label": "Secret", "points": 5, "public": False}]
    db.commit()
    congress_trade(db, "C000127", "AAPL", buy=True)
    html = logged_in.get("/stocks/aapl").text
    assert "Apple Inc." in html
    assert "Timothy D Cook (Chief Executive Officer) sold 4,000 shares at an average of $251.50" in html
    assert "holds 6,000 shares afterwards" in html
    assert '<span class="tag">CEO</span>' in html and "Secret" not in html
    assert "Sen. Maria Cantwell</a> (D-WA) bought Apple Inc. · owner: Spouse" in html
    assert "$15,001 – $50,000" in html
    assert 'href="https://www.sec.gov/Archives/edgar/data/320193/x-index.htm"' in html


def test_company_page_empty_and_unknown(logged_in, seeded):
    assert "No buys or sells yet" in logged_in.get("/stocks/XOM").text
    assert logged_in.get("/stocks/NOPE").status_code == 404


def test_held_trades_are_marked(logged_in, seeded, db):
    trade = insider_trade(db, "AAPL", value=60_000_000)
    trade.needs_review, trade.review_reason = True, "Over $50M: check the filing before alerting"
    db.commit()
    assert "Held for review" in logged_in.get("/stocks/AAPL").text


def test_politician_page_and_latest_trade_on_card(logged_in, seeded, db):
    congress_trade(db, "P000197", "NVDA", buy=False, low=1_000_001, high=5_000_000, days_ago=2)
    card = logged_in.get("/politicians/cards", params={"q": "pelosi"}).text
    assert ">NVDA<" in card and "$1,000,001 – $5,000,000" in card and "reported 2d ago" in card
    page = logged_in.get("/politicians/P000197").text
    assert "Nancy Pelosi" in page and "Representative · Democrat · California, district 11" in page
    assert "Nvidia" in page
    assert logged_in.get("/politicians/NOPE").status_code == 404


def test_politician_page_marks_led_committees(logged_in, seeded):
    html = logged_in.get("/politicians/C000127").text
    assert "Commerce, Science, and Transportation · leads" in html


def test_alerts_page_shows_only_my_alerts(logged_in, seeded, db):
    me = db.scalar(select(User).where(User.telegram_id == 42))
    other = User(telegram_id=99, first_name="Other")
    db.add(other)
    db.commit()
    mine = insider_trade(db, "NVDA", days_ago=1)
    theirs = insider_trade(db, "XOM", buy=False, days_ago=1)
    pol = congress_trade(db, "C000127", "LMT")
    db.add_all([
        Alert(user_id=me.id, trade_id=mine.id, status="sent", sent_at=datetime(2026, 9, 26, 11, 2)),
        Alert(user_id=me.id, trade_id=pol.id, status="failed", error="Couldn't reach Telegram."),
        Alert(user_id=other.id, trade_id=theirs.id, status="sent"),
    ])
    db.commit()

    html = logged_in.get("/alerts").text
    assert "NVDA" in html and "Delivered Sep 26, 11:02 AM UTC" in html
    assert "Lockheed Martin" in html and "Not delivered: Couldn&#39;t reach Telegram." in html
    assert "XOM" not in html
