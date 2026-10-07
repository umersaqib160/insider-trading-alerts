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
    assert trade.score == 43  # size 35 + planned sale 0 + director 8
    assert _labels(trade) == {"$10M+": 35, "Pre-planned sale": 0, "Director": 8}
    assert trade.needs_review and trade.review_reason.startswith("Over $50M")


def test_ten_percent_owner_buy_is_notable(db, seeded):
    # Berkshire Hathaway buying $136M of Lennar as a 10% owner.
    trade = insider_trade(db, "AAPL", buy=True, value=136_000_000, role="10% Owner", name="Berkshire Hathaway Inc")
    score_trades(db, [trade], watchlist=set())
    assert trade.score == 60 and trade.score >= NOTABLE_THRESHOLD
    assert trade.public_tags == ["$10M+", "10% owner"]  # "Open-market buy" is internal; the pill already says Buy


def test_ceo_buy_with_a_cluster_scores_80(db, seeded):
    others = [insider_trade(db, "NVDA", buy=True, value=300_000, role="Director", name=n) for n in ("A Director", "B Director")]
    ceo = insider_trade(db, "NVDA", buy=True, value=2_000_000, role="President and CEO")
    score_trades(db, others + [ceo], watchlist=set())
    assert ceo.score == 80  # 15 + 20 + 20 + 25
    assert "3 insiders buying within 14 days" in ceo.public_tags


def test_earlier_trades_are_rescored_when_a_cluster_forms(db, seeded):
    first = insider_trade(db, "NVDA", buy=True, value=300_000, role="Director", name="A")
    score_trades(db, [first], watchlist=set())
    assert first.score == 33  # 5 + 20 + 8
    later = [insider_trade(db, "NVDA", buy=True, value=300_000, role="Director", name=n) for n in ("B", "C")]
    score_trades(db, later, watchlist=set())
    assert first.score == 58  # gained the 25-point cluster


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
             "Director, 10% Owner": "Director", "10% Owner": "10% owner", "Vice Chair": "Senior officer"}
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
