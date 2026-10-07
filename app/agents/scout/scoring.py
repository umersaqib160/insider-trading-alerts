"""The "notable" score: how interesting a trade is, 0-100, with the reasons behind it.

Every point a trade earns is stored as a tag. Public tags are plain facts
about the filing ("CEO", "$5M+", "3 insiders buying within 14 days") and are
shown to users; the number itself is only used internally to pick what the
marketing agents talk about. Users always get alerts for what they star,
whatever the score.

All weights live in this file so they're easy to tune after the weekly
top-10 review.
"""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import BUY, CONGRESS_SOURCES, SOURCE_FORM4, Politician, Trade

NOTABLE_THRESHOLD = 60
CLUSTER_WINDOW_DAYS = 14
REVIEW_VALUE = 50_000_000
REVIEW_APPROVED = "approved"

INSIDER_SIZE = [(10_000_000, 35, "$10M+"), (5_000_000, 25, "$5M+"), (1_000_000, 15, "$1M+"), (100_000, 5, "$100K+")]
# Congress reports ranges; we score on the bottom of the range.
CONGRESS_SIZE = [(1_000_000, 35, "$1M+"), (250_000, 25, "$250K+"), (50_000, 15, "$50K+"), (15_000, 5, "$15K+")]

INSIDER_BUY = 20
INSIDER_UNPLANNED_SALE = 5
INSIDER_PLANNED_SALE = 0
CONGRESS_BUY = 10
CONGRESS_SALE = 5

ROLE_TOP = 20  # CEO, CFO, chair
ROLE_OFFICER = 10
ROLE_DIRECTOR = 8
ROLE_TEN_PERCENT = 5
WATCHLIST_MEMBER = 20
COMMITTEE_LEADER = 10
COMMITTEE_LINK = 15
INSIDER_CLUSTER = 25  # 3+ different insiders buying the same company
INSIDER_CLUSTER_MIN = 3
CONGRESS_CLUSTER = 15  # 2+ members trading the same stock
CONGRESS_CLUSTER_MIN = 2

# Which industries each committee oversees, matched against a company's sector and industry text.
_FINANCE = ("financials", "bank", "insurance", "capital markets", "real estate", "reit", "credit", "asset management")
_ENERGY = ("energy", "oil", "gas", "petroleum", "utilities", "electric", "coal", "pipeline")
_HEALTH = ("health care", "pharmaceutical", "biotech", "biological", "medical", "managed health", "life sciences")
_DEFENSE = ("aerospace", "defense", "aircraft", "guided missile", "ordnance", "search, detection")
_FARM = ("agricultur", "farm", "fertilizer", "food", "tobacco", "grain", "meat")
_TECH = ("semiconductor", "software", "internet", "computer", "telecom", "communication", "information technology")
_TRANSPORT = ("airline", "air freight", "railroad", "trucking", "transport", "automobile", "motor vehicle", "shipping")
COMMITTEE_INDUSTRIES: dict[str, tuple[str, ...]] = {
    "Armed Services": _DEFENSE,
    "Intelligence": _DEFENSE,
    "Homeland Security": _DEFENSE,
    "Homeland Security and Governmental Affairs": _DEFENSE,
    "Financial Services": _FINANCE,
    "Banking, Housing, and Urban Affairs": _FINANCE,
    "Energy and Commerce": _ENERGY + _HEALTH + ("telecom", "communication", "media"),
    "Energy and Natural Resources": _ENERGY + ("mining", "metals", "gold", "silver", "copper"),
    "Natural Resources": ("oil", "gas", "mining", "metals", "coal", "timber", "gold", "copper"),
    "Agriculture": _FARM,
    "Agriculture, Nutrition, and Forestry": _FARM,
    "Health, Education, Labor, and Pensions": _HEALTH,
    "Veterans' Affairs": _HEALTH,
    "Commerce, Science, and Transportation": _TRANSPORT + _TECH,
    "Transportation and Infrastructure": _TRANSPORT + ("construction", "engineering", "machinery"),
    "Science, Space, and Technology": ("aerospace",) + _TECH + ("biotech",),
    "Environment and Public Works": ("utilities", "construction", "waste", "water", "engineering"),
}

WATCHLIST_FILE = Path(__file__).resolve().parents[2] / "data" / "watchlist_politicians.txt"


@dataclass
class Score:
    score: int
    tags: list[dict]
    review_reason: str | None


def load_watchlist(path: Path = WATCHLIST_FILE) -> set[str]:
    """Names of politicians to treat as high-profile. One per line; # starts a comment."""
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text().splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.add(name.lower())
    return names


def on_watchlist(politician: Politician, watchlist: set[str]) -> bool:
    return (politician.full_name.lower() in watchlist
            or f"{politician.first_name} {politician.last_name}".lower() in watchlist)


def _tag(label: str, points: int, public: bool = True) -> dict:
    return {"label": label, "points": points, "public": public}


def _size_tag(value: float | None, scale) -> dict | None:
    for threshold, points, label in scale:
        if value and value >= threshold:
            return _tag(label, points)
    return None


def _role_tag(title: str) -> dict | None:
    lowered = f" {title.lower()} "
    if "chief executive" in lowered or " ceo" in lowered:
        return _tag("CEO", ROLE_TOP)
    if "chief financial" in lowered or " cfo" in lowered:
        return _tag("CFO", ROLE_TOP)
    if "chair" in lowered and "vice chair" not in lowered:
        return _tag("Chair", ROLE_TOP)
    officer_parts = [p.strip() for p in title.split(",") if p.strip() and p.strip() not in ("Director", "10% Owner")]
    if officer_parts:
        return _tag("Senior officer", ROLE_OFFICER)
    if "director" in lowered:
        return _tag("Director", ROLE_DIRECTOR)
    if "10% owner" in lowered:
        return _tag("10% owner", ROLE_TEN_PERCENT)
    return None


def committee_links(politician: Politician, sector: str, industry: str) -> list[str]:
    text = f"{sector} {industry}".lower()
    return [c for c in politician.committees
            if any(keyword in text for keyword in COMMITTEE_INDUSTRIES.get(c, ()))]


def _insider_cluster(db: Session, trade: Trade) -> int:
    window = timedelta(days=CLUSTER_WINDOW_DAYS)
    return db.scalar(select(func.count(func.distinct(Trade.actor_name))).where(
        Trade.source == SOURCE_FORM4, Trade.direction == BUY, Trade.company_id == trade.company_id,
        Trade.trade_date.between(trade.trade_date - window, trade.trade_date + window),
    )) or 0


def _congress_cluster(db: Session, trade: Trade) -> int:
    window = timedelta(days=CLUSTER_WINDOW_DAYS)
    return db.scalar(select(func.count(func.distinct(Trade.actor_name))).where(
        Trade.source.in_(CONGRESS_SOURCES), Trade.ticker == trade.ticker,
        Trade.trade_date.between(trade.trade_date - window, trade.trade_date + window),
    )) or 0


def review_reason(trade: Trade) -> str | None:
    """Trades to hold for a human look before any alert goes out."""
    if trade.value_low and trade.value_low >= REVIEW_VALUE:
        return "Over $50M: check the filing before alerting"
    if trade.trade_date > trade.filed_date:
        return "Trade date is after the filing date"
    if (trade.filed_date - trade.trade_date).days > 400:
        return "Trade happened over a year before it was filed"
    if trade.insider and trade.insider.avg_price is not None and not (0 < trade.insider.avg_price < 100_000):
        return "Unusual share price"
    return None


def score_trade(db: Session, trade: Trade, watchlist: set[str]) -> Score:
    tags: list[dict] = []
    if trade.source == SOURCE_FORM4:
        if size := _size_tag(trade.value_low, INSIDER_SIZE):
            tags.append(size)
        if trade.is_buy:
            tags.append(_tag("Open-market buy", INSIDER_BUY, public=False))
        elif trade.insider and trade.insider.is_10b5_1:
            tags.append(_tag("Pre-planned sale", INSIDER_PLANNED_SALE))
        else:
            tags.append(_tag("Unplanned sale", INSIDER_UNPLANNED_SALE))
        if role := _role_tag(trade.actor_role):
            tags.append(role)
        if trade.is_buy and trade.company_id:
            buyers = _insider_cluster(db, trade)
            if buyers >= INSIDER_CLUSTER_MIN:
                tags.append(_tag(f"{buyers} insiders buying within {CLUSTER_WINDOW_DAYS} days", INSIDER_CLUSTER))
    else:
        if size := _size_tag(trade.value_low, CONGRESS_SIZE):
            tags.append(size)
        tags.append(_tag("Purchase" if trade.is_buy else "Sale",
                         CONGRESS_BUY if trade.is_buy else CONGRESS_SALE, public=False))
        politician = trade.politician
        if politician:
            if on_watchlist(politician, watchlist):
                tags.append(_tag("High-profile member", WATCHLIST_MEMBER, public=False))
            elif politician.led_committees:
                tags.append(_tag(f"Leads the {politician.led_committees[0]} committee", COMMITTEE_LEADER))
            if trade.company:
                links = committee_links(politician, trade.company.sector, trade.company.industry)
                if links:
                    tags.append(_tag(f"Sits on {links[0]}", COMMITTEE_LINK))
        if trade.ticker:
            members = _congress_cluster(db, trade)
            if members >= CONGRESS_CLUSTER_MIN:
                tags.append(_tag(f"{members} members of Congress traded {trade.ticker} within "
                                 f"{CLUSTER_WINDOW_DAYS} days", CONGRESS_CLUSTER))
    score = min(100, sum(t["points"] for t in tags))
    return Score(score=score, tags=tags, review_reason=review_reason(trade))


def related_recent_trades(db: Session, trades: list[Trade]) -> list[Trade]:
    """Trades whose cluster count may have changed because of these new ones."""
    company_ids = {t.company_id for t in trades if t.source == SOURCE_FORM4 and t.is_buy and t.company_id}
    tickers = {t.ticker for t in trades if t.source in CONGRESS_SOURCES and t.ticker}
    if not trades or not (company_ids or tickers):
        return []
    earliest = min(t.trade_date for t in trades) - timedelta(days=CLUSTER_WINDOW_DAYS)
    related = []
    if company_ids:
        related += db.scalars(select(Trade).where(
            Trade.source == SOURCE_FORM4, Trade.direction == BUY, Trade.company_id.in_(company_ids),
            Trade.trade_date >= earliest)).all()
    if tickers:
        related += db.scalars(select(Trade).where(
            Trade.source.in_(CONGRESS_SOURCES), Trade.ticker.in_(tickers), Trade.trade_date >= earliest)).all()
    new_ids = {t.id for t in trades}
    return [t for t in related if t.id not in new_ids]


def score_trades(db: Session, new_trades: list[Trade], watchlist: set[str] | None = None) -> int:
    """Score new trades (holding any that look wrong), and re-score older trades in the same clusters."""
    watchlist = load_watchlist() if watchlist is None else watchlist
    for trade in new_trades:
        result = score_trade(db, trade, watchlist)
        trade.score, trade.tags = result.score, result.tags
        if result.review_reason:
            trade.needs_review, trade.review_reason = True, result.review_reason
    for trade in related_recent_trades(db, new_trades):
        result = score_trade(db, trade, watchlist)
        trade.score, trade.tags = result.score, result.tags  # review flags are only set once, on arrival
    db.commit()
    return len(new_trades)


def notable(trade: Trade) -> bool:
    return trade.score >= NOTABLE_THRESHOLD
