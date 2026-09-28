from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.alerts import MAX_SEND_ATTEMPTS, create_alerts, format_trade_message, send_pending_alerts
from app.ingest import days_to_ingest, ingest_day
from app.jobs import run_daily
from app.models import (
    ALERT_FAILED, ALERT_PENDING, ALERT_SENT, TELEGRAM_BLOCKED, TELEGRAM_DISCONNECTED,
    Alert, Company, CompanyWatch, IngestedDay, Trade, User,
)
from app.sec import EdgarError, daily_index_path
from app.telegram import TelegramSendError

from .conftest import FIXTURES
from .form4 import APPLE_CEO_SALE, APPLE_GRANT_ONLY, NVIDIA_DIRECTOR_BUY

FRIDAY = date(2026, 9, 25)
MONDAY = date(2026, 9, 28)


class FakeEdgar:
    def __init__(self, files: dict[str, str] | None = None, fail_on: str | None = None):
        self.files = files or {}
        self.fail_on = fail_on
        self.requested: list[str] = []

    def get_text(self, path: str) -> str | None:
        self.requested.append(path)
        if self.fail_on and self.fail_on in path:
            raise EdgarError("SEC EDGAR returned HTTP 503")
        return self.files.get(path)


def friday_edgar() -> FakeEdgar:
    return FakeEdgar({
        daily_index_path(FRIDAY): (FIXTURES / "form_index_sample.idx").read_text(),
        "/Archives/edgar/data/320193/0001140361-26-000101.txt": APPLE_CEO_SALE,
        "/Archives/edgar/data/1045810/0001045810-26-000202.txt": NVIDIA_DIRECTOR_BUY,
        "/Archives/edgar/data/320193/0001140361-26-000303.txt": APPLE_GRANT_ONLY,
    })


@pytest.fixture
def companies(db):
    apple = Company(ticker="AAPL", name="Apple Inc.", sector="Information Technology", cik="0000320193")
    nvidia = Company(ticker="NVDA", name="Nvidia", sector="Information Technology", cik="0001045810")
    db.add_all([apple, nvidia, Company(ticker="XOM", name="Exxon Mobil", sector="Energy", cik="0000034088")])
    db.commit()
    return {"AAPL": apple, "NVDA": nvidia}


def add_user(db, telegram_id: int, *tickers: str, status: str = "connected") -> User:
    user = User(telegram_id=telegram_id, first_name=f"User{telegram_id}", telegram_status=status)
    db.add(user)
    db.commit()
    for ticker in tickers:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        db.add(CompanyWatch(user_id=user.id, company_id=company.id))
    db.commit()
    return user


# ---------- ingestion ----------

def test_days_to_ingest_skips_weekends_today_and_processed_days(db):
    assert days_to_ingest(db, MONDAY) == [date(2026, 9, 23), date(2026, 9, 24), FRIDAY]
    db.add(IngestedDay(source="sec_form4", day=date(2026, 9, 24)))
    db.commit()
    assert days_to_ingest(db, MONDAY) == [date(2026, 9, 23), FRIDAY]


def test_ingest_day_stores_buys_and_sells_for_tracked_issuers(db, companies):
    edgar = friday_edgar()
    result = ingest_day(db, edgar, FRIDAY, MONDAY)

    assert result.filings == 3  # listed twice for Apple's CEO sale, once each for the others; 4/A and untracked ignored
    assert sorted((t.ticker, t.code) for t in result.trades) == [("AAPL", "S"), ("NVDA", "P")]
    sale = db.scalar(select(Trade).where(Trade.ticker == "AAPL"))
    assert (sale.filed_date, sale.trade_date, sale.shares, sale.is_10b5_1) == (FRIDAY, date(2026, 9, 23), 4000, True)
    assert sale.company_id == companies["AAPL"].id
    assert sale.source_url.endswith("/320193/000114036126000101/0001140361-26-000101-index.htm")
    assert not any("999999" in p or "000505" in p for p in edgar.requested)
    day = db.get(IngestedDay, ("sec_form4", FRIDAY))
    assert (day.filings, day.trades) == (3, 2)


def test_ingest_day_skips_filings_already_stored(db, companies):
    ingest_day(db, friday_edgar(), FRIDAY, MONDAY)
    db.delete(db.get(IngestedDay, ("sec_form4", FRIDAY)))
    db.commit()
    again = ingest_day(db, friday_edgar(), FRIDAY, MONDAY)
    assert again.trades == []
    assert db.scalar(select(func.count()).select_from(Trade)) == 2


def test_missing_recent_index_is_retried_but_old_one_is_skipped(db, companies):
    recent = ingest_day(db, FakeEdgar(), FRIDAY, MONDAY)
    assert recent.published is False
    assert db.get(IngestedDay, ("sec_form4", FRIDAY)) is None

    ingest_day(db, FakeEdgar(), FRIDAY, MONDAY + timedelta(days=7))
    assert db.get(IngestedDay, ("sec_form4", FRIDAY)) is not None


# ---------- alerts ----------

def _ingest(db) -> list[Trade]:
    return ingest_day(db, friday_edgar(), FRIDAY, MONDAY).trades


def test_format_trade_message(db, companies):
    sale = next(t for t in _ingest(db) if t.ticker == "AAPL")
    message = format_trade_message(sale)
    assert message.splitlines() == [
        "<b>SELL · AAPL</b> (Apple Inc.)",
        "Timothy D Cook (Chief Executive Officer) sold 4,000 shares (avg $251.50)",
        "Value: $1.0M",
        "Traded Sep 23 · Filed Sep 25",
        "Pre-planned under a Rule 10b5-1 trading plan",
        '<a href="https://www.sec.gov/Archives/edgar/data/320193/000114036126000101/0001140361-26-000101-index.htm">View the Form 4 on SEC EDGAR</a>',
    ]


def test_format_trade_message_escapes_html(db, companies):
    trade = _ingest(db)[0]
    trade.insider_name = "Evil <b>Corp</b> & Co"
    assert "Evil &lt;b&gt;Corp&lt;/b&gt; &amp; Co" in format_trade_message(trade)


def test_create_alerts_only_for_connected_watchers(db, companies):
    watcher = add_user(db, 1, "AAPL")
    add_user(db, 2, "NVDA", status=TELEGRAM_DISCONNECTED)
    add_user(db, 3)  # watches nothing
    trades = _ingest(db)

    assert create_alerts(db, trades, MONDAY) == 1
    alert = db.scalar(select(Alert))
    assert (alert.user_id, alert.trade.ticker, alert.status) == (watcher.id, "AAPL", ALERT_PENDING)
    assert create_alerts(db, trades, MONDAY) == 0


def test_create_alerts_skips_stale_filings(db, companies):
    add_user(db, 1, "AAPL", "NVDA")
    assert create_alerts(db, _ingest(db), MONDAY + timedelta(days=30)) == 0


def test_send_pending_alerts_delivers_once(db, companies, telegram):
    user = add_user(db, 77, "AAPL", "NVDA")
    create_alerts(db, _ingest(db), MONDAY)

    result = send_pending_alerts(db, telegram)
    assert (result.sent, result.failed) == (2, 0)
    assert [chat for chat, _ in telegram.sent] == [77, 77]
    assert all(a.status == ALERT_SENT and a.sent_at for a in db.scalars(select(Alert)))
    assert send_pending_alerts(db, telegram).sent == 0
    assert user.telegram_status == "connected"


def test_blocked_bot_stops_delivery_for_that_user(db, companies, telegram):
    user = add_user(db, 1, "AAPL", "NVDA")
    create_alerts(db, _ingest(db), MONDAY)
    telegram.error = TelegramSendError("blocked", blocked=True)

    result = send_pending_alerts(db, telegram)
    assert (result.sent, result.failed) == (0, 1)  # second alert skipped once the user is marked blocked
    db.refresh(user)
    assert user.telegram_status == TELEGRAM_BLOCKED


def test_failed_sends_are_retried_a_limited_number_of_times(db, companies, telegram):
    add_user(db, 1, "AAPL")
    create_alerts(db, _ingest(db), MONDAY)
    telegram.error = TelegramSendError("Couldn't reach Telegram.")
    for _ in range(MAX_SEND_ATTEMPTS + 2):
        send_pending_alerts(db, telegram)
    alert = db.scalar(select(Alert))
    assert (alert.status, alert.attempts, alert.error) == (ALERT_FAILED, MAX_SEND_ATTEMPTS, "Couldn't reach Telegram.")

    telegram.error = None
    alert.attempts = 1
    db.commit()
    assert send_pending_alerts(db, telegram).sent == 1


# ---------- daily job ----------

def test_run_daily_end_to_end(db, companies, telegram):
    add_user(db, 55, "NVDA")
    edgar = friday_edgar()

    report = run_daily(db, edgar, telegram, MONDAY, refresh_refdata=False)
    assert [d.day for d in report.days] == [date(2026, 9, 23), date(2026, 9, 24), FRIDAY]
    assert report.alerts_created == 1 and report.dispatch.sent == 1
    assert telegram.sent[0][0] == 55
    assert telegram.sent[0][1].startswith("<b>BUY · NVDA</b> (Nvidia)")
    assert "3 tracked filings, 2 buys/sells" in "\n".join(report.lines())

    # Friday is done; Sep 24's index (absent here) is still inside the grace period, so it's checked again.
    rerun = run_daily(db, edgar, telegram, MONDAY, refresh_refdata=False)
    assert [(d.day, d.published) for d in rerun.days] == [(date(2026, 9, 24), False)]
    assert len(telegram.sent) == 1


def test_run_daily_backfill_mode_sends_nothing(db, companies, telegram):
    add_user(db, 55, "NVDA")
    report = run_daily(db, friday_edgar(), telegram, MONDAY, refresh_refdata=False, send_alerts=False)
    assert len(report.days[-1].trades) == 2
    assert telegram.sent == [] and db.scalar(select(Alert)) is None


def test_run_daily_stops_at_an_outage_and_retries_later(db, companies, telegram):
    edgar = friday_edgar()
    edgar.fail_on = "form.20260924"
    report = run_daily(db, edgar, telegram, MONDAY, refresh_refdata=False)
    assert [d.day for d in report.days] == [date(2026, 9, 23)]
    assert report.errors == ["SEC EDGAR returned HTTP 503"]
    assert days_to_ingest(db, MONDAY) == [date(2026, 9, 24), FRIDAY]
