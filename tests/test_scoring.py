"""The worked examples from the plan, plus the rules behind them."""

from datetime import timedelta

from app.agents.scout.scoring import NOTABLE_THRESHOLD, committee_links, review_reason, score_trades
from app.formatting import market_today
from app.models import Politician

from .factories import congress_trade, insider_trade


def _labels(trade) -> dict[str, int]:
    return {t["label"]: t["points"] for t in trade.tags}


def test_planned_director_sale_is_not_notable_but_is_held(db, seeded):
    # Henry Samueli (Director), Broadcom: pre-planned sale of $250M.
    trade = insider_trade(db, "AAPL", buy=False, value=250_000_000, role="Director", plan=True)
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 20  # size 0 + planned sale 0 + director 20; no S&P points on sales
    assert _labels(trade) == {"$10M+": 0, "Pre-planned sale": 0, "Director": 20}
    assert trade.needs_review and trade.review_reason.startswith("Over $50M")


def test_sales_are_never_notable(db, seeded):
    trade = insider_trade(db, "NVDA", buy=False, value=40_000_000, role="President and CEO")
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 5 and trade.score < NOTABLE_THRESHOLD  # unplanned sale 0 + CEO 5
    assert trade.public_tags == ["$10M+", "Unplanned sale", "CEO"]


def test_director_buy_at_a_top_200_sp500_company_is_notable(db, seeded):
    trade = insider_trade(db, "AAPL", buy=True, value=500_000, role="Director", name="Jane Director")
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 75  # buy 30 + director 20 + S&P top 200 25
    assert trade.public_tags == ["$100K+", "Director", "S&P 500"]  # "Open-market buy" is internal


def test_sp500_tiers_and_buys_outside_the_index(db, seeded):
    lower = insider_trade(db, "LMT", buy=True, value=200_000, role="EVP, Operations")  # S&P rank 250
    outside = insider_trade(db, "SMCO", buy=True, value=5_000_000, role="EVP, Operations")
    ceo = insider_trade(db, "NVDA", buy=True, value=2_000_000, role="President and CEO")
    score_trades(db, [lower, outside, ceo], watchlist=set())
    assert lower.score == 65  # 30 + officer 20 + S&P 201-500 15
    assert outside.score == 50 and outside.score < NOTABLE_THRESHOLD  # size earns nothing
    assert ceo.score == 60  # 30 + CEO 5 + top 200 25


def test_ten_percent_owner_buy_is_not_notable(db, seeded):
    # Berkshire Hathaway buying $136M as a 10% owner: a fact worth showing, but 10% owners don't predict moves.
    trade = insider_trade(db, "AAPL", buy=True, value=136_000_000, role="10% Owner", name="Berkshire Hathaway Inc")
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 55  # 30 + 10% owner 0 + S&P top 200 25
    assert trade.public_tags == ["$10M+", "10% owner", "S&P 500"]


def test_cluster_of_officers_and_directors_adds_5(db, seeded):
    first = insider_trade(db, "SMCO", buy=True, value=100_000, role="Director", name="A")
    score_trades(db, [first], watchlist=set())
    assert first.score == 50
    later = [insider_trade(db, "SMCO", buy=True, value=100_000, role="Director", name=n) for n in ("B", "C")]
    score_trades(db, later, watchlist=set())
    assert first.score == 55  # earlier trades are re-scored when a cluster forms ($300K combined)
    assert "3 insiders buying within 14 days" in first.public_tags


def test_cluster_ignores_token_buys_owners_and_small_totals(db, seeded):
    token = [insider_trade(db, "SMCO", buy=True, value=v, role="Director", name=n)
             for n, v in (("A", 200_000), ("B", 200_000), ("C", 5_000))]  # C's $5K buy doesn't count
    owners = [insider_trade(db, "XOM", buy=True, value=1_000_000, role=r, name=n)
              for n, r in (("Fund", "10% Owner"), ("D", "Director"), ("E", "Director"))]  # 10% owners don't count
    small = [insider_trade(db, "LMT", buy=True, value=50_000, role="Director", name=n) for n in "FGH"]  # $150K total
    score_trades(db, token + owners + small, watchlist=set())
    assert all("insiders buying" not in " ".join(t.public_tags) for t in token + owners + small)


def test_sales_never_form_insider_clusters(db, seeded):
    sales = [insider_trade(db, "NVDA", buy=False, value=300_000, role="Director", name=n) for n in "ABC"]
    score_trades(db, sales, watchlist=set())
    assert all("insiders buying" not in " ".join(t.public_tags) for t in sales)


def test_senator_on_armed_services_buying_a_defense_stock(db, seeded):
    trade = congress_trade(db, "B001236", "LMT", buy=True, low=50_001, high=100_000)
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 40  # 15 + 10 + 15
    assert "Sits on Armed Services" in trade.public_tags

    again = congress_trade(db, "B001236", "LMT", buy=True, low=50_001, high=100_000)
    score_trades(db, [again], watchlist={"john boozman"})
    assert again.score >= 60  # +20 for being on the high-profile list (internal tag)
    assert "High-profile member" not in again.public_tags


def test_committee_leader_and_congress_cluster(db, seeded):
    a = congress_trade(db, "C000127", "XOM", buy=False, low=15_001, high=50_000)
    b = congress_trade(db, "P000197", "XOM", buy=True, low=15_001, high=50_000)
    score_trades(db, [a, b], watchlist=set())
    assert "Leads the Commerce, Science, and Transportation committee" in a.public_tags
    assert "2 members of Congress traded XOM within 14 days" in b.public_tags


def test_role_detection(db, seeded):
    cases = {"Chief Financial Officer": "CFO", "Chairman of the Board": "Chair", "EVP, General Counsel": "Senior officer",
             "Director, 10% Owner": "Director", "10% Owner": "10% owner", "Vice Chair": "Senior officer",
             "Co-COB and Co-CEO, Director": "CEO", "EVP & CFO": "CFO", "COB": "Chair", "Chief Commercial Officer": "Senior officer"}
    for role, label in cases.items():
        trade = insider_trade(db, "AAPL", buy=False, value=10, role=role)
        score_trades(db, [trade], watchlist=set())
        assert label in trade.public_tags, role


def test_committee_links():
    p = Politician(committees=["Armed Services", "Budget", "Financial Services"])
    assert committee_links(p, "Industrials", "Aerospace & Defense") == ["Armed Services"]
    assert committee_links(p, "Financials", "Regional Banks") == ["Financial Services"]
    assert committee_links(p, "Information Technology", "Semiconductors") == []


def test_review_rules(db, seeded):
    today = market_today()
    assert review_reason(insider_trade(db, "AAPL", value=1_000)) is None
    assert "after the filing" in review_reason(insider_trade(db, "AAPL", filed=today, traded=today + timedelta(days=1)))
    assert "over a year" in review_reason(insider_trade(db, "AAPL", filed=today, traded=today - timedelta(days=500)))
    assert "share price" in review_reason(insider_trade(db, "AAPL", avg_price=250_000))
