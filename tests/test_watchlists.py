from sqlalchemy import func, select

from app.models import CompanyWatch, PoliticianWatch

from .conftest import HX, login_params, toast_of


def test_stocks_page_lists_only_current_sp500(logged_in, seeded):
    html = logged_in.get("/stocks").text
    assert "Apple Inc." in html and "Exxon Mobil" in html
    assert "Departed Co" not in html
    assert "S&amp;P 500 · 3 companies" in html


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
