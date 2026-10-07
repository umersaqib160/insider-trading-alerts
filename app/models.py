from datetime import date, datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

TELEGRAM_CONNECTED = "connected"
TELEGRAM_DISCONNECTED = "disconnected"
TELEGRAM_BLOCKED = "blocked"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "AS": "American Samoa", "DC": "District of Columbia", "GU": "Guam",
    "MP": "Northern Mariana Islands", "PR": "Puerto Rico", "VI": "U.S. Virgin Islands",
}
PARTY_NAMES = {"D": "Democrat", "R": "Republican", "I": "Independent"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _initials(*parts: str | None) -> str:
    words = [p for p in parts if p]
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()




class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    telegram_status: Mapped[str] = mapped_column(String(16), default=TELEGRAM_CONNECTED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or self.username or "You"

    @property
    def initials(self) -> str:
        return _initials(self.first_name, self.last_name) if self.first_name else _initials(self.username)


class Company(Base):
    """A US company listed on Nasdaq, NYSE or Cboe, one row per SEC CIK."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    other_tickers: Mapped[list[str]] = mapped_column(JSON, default=list)
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(16), default="")
    sector: Mapped[str] = mapped_column(String(64), default="")
    industry: Mapped[str] = mapped_column(String(128), default="")
    sic_code: Mapped[int | None] = mapped_column(Integer)
    industry_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    in_sp500: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Politician(Base):
    __tablename__ = "politicians"

    id: Mapped[int] = mapped_column(primary_key=True)
    bioguide_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[str] = mapped_column(String(64), default="")
    chamber: Mapped[str] = mapped_column(String(8))  # "senate" | "house"
    party: Mapped[str] = mapped_column(String(1))  # "D" | "R" | "I"
    state: Mapped[str] = mapped_column(String(2))
    district: Mapped[int | None] = mapped_column(Integer)
    committees: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Committees this member chairs or leads for the minority (ranking member).
    led_committees: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def title(self) -> str:
        return "Sen." if self.chamber == "senate" else "Rep."

    @property
    def role_label(self) -> str:
        return "Senator" if self.chamber == "senate" else "Representative"

    @property
    def short_label(self) -> str:
        return f"{self.party}-{self.state}"

    @property
    def seat_label(self) -> str:
        if self.chamber == "senate" or self.district is None:
            return STATE_NAMES.get(self.state, self.state)
        seat = "at-large" if self.district == 0 else f"district {self.district}"
        return f"{STATE_NAMES.get(self.state, self.state)}, {seat}"

    @property
    def party_name(self) -> str:
        return PARTY_NAMES.get(self.party, self.party)

    @property
    def initials(self) -> str:
        return _initials(self.first_name, self.last_name)


class CompanyWatch(Base):
    __tablename__ = "company_watches"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PoliticianWatch(Base):
    __tablename__ = "politician_watches"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    politician_id: Mapped[int] = mapped_column(ForeignKey("politicians.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


SOURCE_FORM4 = "sec_form4"
SOURCE_HOUSE = "house"
SOURCE_SENATE = "senate"
CONGRESS_SOURCES = (SOURCE_HOUSE, SOURCE_SENATE)

BUY = "buy"
SELL = "sell"

ALERT_PENDING = "pending"
ALERT_SENT = "sent"
ALERT_FAILED = "failed"


class Trade(Base):
    """What every trade has in common, whoever made it. Source-specific fields live in the detail tables."""

    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_trades_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    # Stable id within the source, so re-fetching never stores a trade twice.
    external_id: Mapped[str] = mapped_column(String(64))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    politician_id: Mapped[int | None] = mapped_column(ForeignKey("politicians.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), default="", index=True)
    asset_name: Mapped[str] = mapped_column(String(256), default="")
    actor_name: Mapped[str] = mapped_column(String(256))
    actor_role: Mapped[str] = mapped_column(String(256), default="")
    direction: Mapped[str] = mapped_column(String(4))
    # Insiders report exact amounts (low == high); Congress reports ranges (high may be open-ended).
    value_low: Mapped[float | None] = mapped_column(Float)
    value_high: Mapped[float | None] = mapped_column(Float)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    filed_date: Mapped[date] = mapped_column(Date, index=True)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # [{"label": "CEO", "points": 20, "public": true}, ...]
    tags: Mapped[list[dict]] = mapped_column(JSON, default=list)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company | None] = relationship()
    politician: Mapped[Politician | None] = relationship()
    insider: Mapped["InsiderTradeDetail | None"] = relationship(
        back_populates="trade", uselist=False, cascade="all, delete-orphan")
    congress: Mapped["CongressTradeDetail | None"] = relationship(
        back_populates="trade", uselist=False, cascade="all, delete-orphan")

    @property
    def is_buy(self) -> bool:
        return self.direction == BUY

    @property
    def is_insider(self) -> bool:
        return self.source == SOURCE_FORM4

    @property
    def disclosure_lag_days(self) -> int:
        return (self.filed_date - self.trade_date).days

    @property
    def public_tags(self) -> list[str]:
        return [t["label"] for t in self.tags or [] if t.get("public", True)]


class InsiderTradeDetail(Base):
    """One insider's open-market buys or sells in one Form 4, totalled across its transaction lines."""

    __tablename__ = "insider_trade_details"

    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True)
    accession_no: Mapped[str] = mapped_column(String(25), index=True)
    transaction_code: Mapped[str] = mapped_column(String(1))
    shares: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float | None] = mapped_column(Float)
    shares_owned_after: Mapped[float | None] = mapped_column(Float)
    is_10b5_1: Mapped[bool] = mapped_column(Boolean, default=False)

    trade: Mapped[Trade] = relationship(back_populates="insider")


class CongressTradeDetail(Base):
    __tablename__ = "congress_trade_details"

    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True)
    chamber: Mapped[str] = mapped_column(String(8))
    owner: Mapped[str] = mapped_column(String(32), default="")
    amount_range: Mapped[str] = mapped_column(String(64), default="")
    transaction_type: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(512), default="")

    trade: Mapped[Trade] = relationship(back_populates="congress")


class ProcessedFiling(Base):
    """A Form 4 already read, whether or not it held a buy or sell, so it is never fetched twice."""

    __tablename__ = "processed_filings"

    accession_no: Mapped[str] = mapped_column(String(25), primary_key=True)
    filed_date: Mapped[date] = mapped_column(Date, index=True)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("user_id", "trade_id", name="uq_alerts_user_trade"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=ALERT_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
    trade: Mapped[Trade] = relationship()
