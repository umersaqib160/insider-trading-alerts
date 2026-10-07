from datetime import date

from sqlalchemy import select

from app.alerts import MAX_SEND_ATTEMPTS, create_alerts, format_trade_message, send_pending_alerts
from app.formatting import market_today
from app.models import (
    ALERT_FAILED, ALERT_SENT, TELEGRAM_BLOCKED, TELEGRAM_DISCONNECTED,
    Alert, Company, CompanyWatch, Politician, PoliticianWatch, User,
)
from app.telegram import TelegramSendError

from .factories import congress_trade, insider_trade


def add_user(db, telegram_id: int, *, companies=(), politicians=(), status: str = "connected") -> User:
    user = User(telegram_id=telegram_id, first_name=f"User{telegram_id}", telegram_status=status)
    db.add(user)
    db.commit()
    for ticker in companies:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        db.add(CompanyWatch(user_id=user.id, company_id=company.id))
    for bioguide in politicians:
        politician = db.scalar(select(Politician).where(Politician.bioguide_id == bioguide))
        db.add(PoliticianWatch(user_id=user.id, politician_id=politician.id))
    db.commit()
    return user


# ---------- message format ----------

def test_insider_message(db, seeded):
    trade = insider_trade(db, "AAPL", buy=False, value=1_006_000, avg_price=251.5, plan=True,
                          filed=date(2026, 9, 25), traded=date(2026, 9, 23))
    trade.tags = [{"label": "$1M+", "points": 15, "public": True},
                  {"label": "Pre-planned sale", "points": 0, "public": True},
                  {"label": "CEO", "points": 20, "public": True},
                  {"label": "Internal note", "points": 5, "public": False}]
    assert format_trade_message(trade).splitlines() == [
        "🏢 <b>🔴 SELL · AAPL</b> — Apple Inc.",
        "👤 Timothy D Cook · Chief Executive Officer",
        "💵 <b>$1.0M</b> · 4,000 shares @ $251.50",
        "🗓 Pre-planned sale (10b5-1 trading plan)",
        "📅 Traded Sep 23 · Filed Sep 25 (2 days later)",
        "🏷 $1M+ · CEO",
        '🔗 <a href="https://www.sec.gov/Archives/edgar/data/320193/x-index.htm">View the Form 4 on SEC EDGAR</a>',
        "ℹ️ <i>From public filings. Not investment advice.</i>",
    ]


def test_congress_message(db, seeded):
    trade = congress_trade(db, "C000127", "LMT", buy=True, low=50_001, high=100_000, traded_days_before=37)
    trade.tags = [{"label": "Sits on Commerce, Science, and Transportation", "points": 15, "public": True}]
    lines = format_trade_message(trade).splitlines()
    assert lines[0] == "🏛 <b>🟢 BUY · LMT</b> — Lockheed Martin"
    assert lines[1] == "👤 Sen. Maria Cantwell (D-WA)"
    assert lines[2] == "💵 <b>$50,001 – $100,000</b> · Owner: Spouse"
    assert lines[3].endswith("(37 days later)") and "Reported" in lines[3]
    assert lines[4] == "🏷 Sits on Commerce, Science, and Transportation"
    assert "View Senate disclosures" in lines[5]


def test_message_escapes_filing_text(db, seeded):
    trade = insider_trade(db, "AAPL", name="Evil <b>Corp</b> & Co", role="")
    assert "👤 Evil &lt;b&gt;Corp&lt;/b&gt; &amp; Co" in format_trade_message(trade)


# ---------- who gets alerted ----------

def test_alerts_go_to_company_and_politician_watchers(db, seeded):
    company_fan = add_user(db, 1, companies=["NVDA"])
    politician_fan = add_user(db, 2, politicians=["P000197"])
    both = add_user(db, 3, companies=["NVDA"], politicians=["P000197"])
    add_user(db, 4, companies=["NVDA"], status=TELEGRAM_DISCONNECTED)
    add_user(db, 5)

    insider = insider_trade(db, "NVDA")
    congress = congress_trade(db, "P000197", "NVDA")
    assert create_alerts(db, [insider, congress], market_today()) == 5
    pairs = {(a.user_id, a.trade_id) for a in db.scalars(select(Alert))}
    assert pairs == {(company_fan.id, insider.id), (both.id, insider.id),
                     (company_fan.id, congress.id), (politician_fan.id, congress.id), (both.id, congress.id)}
    assert create_alerts(db, [insider, congress], market_today()) == 0


def test_held_and_stale_trades_are_not_alerted(db, seeded):
    add_user(db, 1, companies=["AAPL"])
    held = insider_trade(db, "AAPL")
    held.needs_review = True
    stale = insider_trade(db, "AAPL", days_ago=10)
    db.commit()
    assert create_alerts(db, [held, stale], market_today()) == 0


# ---------- delivery ----------

def test_send_pending_alerts_delivers_once(db, seeded, telegram):
    add_user(db, 77, companies=["AAPL", "NVDA"])
    create_alerts(db, [insider_trade(db, "AAPL"), insider_trade(db, "NVDA")], market_today())
    result = send_pending_alerts(db, telegram)
    assert (result.sent, result.failed) == (2, 0)
    assert [chat for chat, _ in telegram.sent] == [77, 77]
    assert all(a.status == ALERT_SENT and a.sent_at for a in db.scalars(select(Alert)))
    assert send_pending_alerts(db, telegram).sent == 0


def test_blocked_bot_stops_delivery_for_that_user(db, seeded, telegram):
    user = add_user(db, 1, companies=["AAPL", "NVDA"])
    create_alerts(db, [insider_trade(db, "AAPL"), insider_trade(db, "NVDA")], market_today())
    telegram.error = TelegramSendError("blocked", blocked=True)
    result = send_pending_alerts(db, telegram)
    assert (result.sent, result.failed) == (0, 1)
    db.refresh(user)
    assert user.telegram_status == TELEGRAM_BLOCKED


def test_failed_sends_are_retried_a_limited_number_of_times(db, seeded, telegram):
    add_user(db, 1, companies=["AAPL"])
    create_alerts(db, [insider_trade(db, "AAPL")], market_today())
    telegram.error = TelegramSendError("Couldn't reach Telegram.")
    for _ in range(MAX_SEND_ATTEMPTS + 2):
        send_pending_alerts(db, telegram)
    alert = db.scalar(select(Alert))
    assert (alert.status, alert.attempts) == (ALERT_FAILED, MAX_SEND_ATTEMPTS)
    telegram.error = None
    alert.attempts = 1
    db.commit()
    assert send_pending_alerts(db, telegram).sent == 1
    assert db.scalar(select(Alert.status)) == ALERT_SENT
