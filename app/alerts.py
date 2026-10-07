from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .formatting import money, shares, short_date
from .models import (
    ALERT_FAILED, ALERT_PENDING, ALERT_SENT, TELEGRAM_BLOCKED, TELEGRAM_CONNECTED,
    Alert, CompanyWatch, PoliticianWatch, Trade, User, utcnow,
)
from .telegram import TelegramClient, TelegramSendError

# Trades filed longer ago than this are history, not news: store them but don't alert.
ALERT_MAX_AGE_DAYS = 7
MAX_SEND_ATTEMPTS = 3
DISCLAIMER = "ℹ️ <i>From public filings. Not investment advice.</i>"


@dataclass
class DispatchResult:
    sent: int = 0
    failed: int = 0


def value_label(trade: Trade) -> str:
    if trade.congress and trade.congress.amount_range:
        return trade.congress.amount_range.replace(" - ", " – ")
    if trade.value_low is None:
        return "Value not disclosed"
    if trade.value_high is None:
        return f"{money(trade.value_low)}+"
    if trade.value_low == trade.value_high:
        return money(trade.value_low)
    return f"{money(trade.value_low)} – {money(trade.value_high)}"


def _who(trade: Trade) -> str:
    if trade.politician:
        p = trade.politician
        who = f"{p.title} {p.full_name} ({p.short_label})"
    else:
        who = trade.actor_name + (f" · {trade.actor_role}" if trade.actor_role else "")
    return escape(who)


def format_trade_message(trade: Trade) -> str:
    """The Telegram alert. HTML parse mode; every value from a filing is escaped."""
    direction = "🟢 BUY" if trade.is_buy else "🔴 SELL"
    icon = "🏢" if trade.is_insider else "🏛"
    ticker = escape(trade.ticker) if trade.ticker else "—"
    lines = [f"{icon} <b>{direction} · {ticker}</b> — {escape(trade.asset_name or trade.ticker)}", f"👤 {_who(trade)}"]

    if trade.is_insider and trade.insider:
        detail = f"💵 <b>{value_label(trade)}</b> · {shares(trade.insider.shares)} shares"
        if trade.insider.avg_price:
            detail += f" @ ${trade.insider.avg_price:,.2f}"
        lines.append(detail)
        if trade.insider.is_10b5_1:
            lines.append("🗓 Pre-planned sale (10b5-1 trading plan)" if not trade.is_buy
                         else "🗓 Pre-planned (10b5-1 trading plan)")
    else:
        detail = f"💵 <b>{value_label(trade)}</b>"
        if trade.congress and trade.congress.owner and trade.congress.owner.lower() != "self":
            detail += f" · Owner: {escape(trade.congress.owner)}"
        lines.append(detail)

    lag = trade.disclosure_lag_days
    lag_text = "same day" if lag <= 0 else f"{lag} day{'s' if lag != 1 else ''} later"
    filed_word = "Filed" if trade.is_insider else "Reported"
    lines.append(f"📅 Traded {short_date(trade.trade_date)} · {filed_word} {short_date(trade.filed_date)} ({lag_text})")

    tags = [t for t in trade.public_tags if not t.startswith("Pre-planned")]
    if tags:
        lines.append("🏷 " + " · ".join(escape(t) for t in tags))
    source = "the Form 4 on SEC EDGAR" if trade.is_insider else (
        "House disclosures" if trade.source == "house" else "Senate disclosures")
    lines.append(f'🔗 <a href="{escape(trade.source_url)}">View {source}</a>')
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _watchers(db: Session, trade: Trade) -> list[User]:
    conditions = []
    if trade.company_id:
        conditions.append(User.id.in_(select(CompanyWatch.user_id).where(CompanyWatch.company_id == trade.company_id)))
    if trade.politician_id:
        conditions.append(User.id.in_(
            select(PoliticianWatch.user_id).where(PoliticianWatch.politician_id == trade.politician_id)))
    if not conditions:
        return []
    return db.scalars(select(User).where(or_(*conditions), User.telegram_status == TELEGRAM_CONNECTED)).all()


def create_alerts(db: Session, trades: list[Trade], today: date) -> int:
    """Queue one alert per connected user who starred the company or the politician behind each recent trade."""
    cutoff = today - timedelta(days=ALERT_MAX_AGE_DAYS)
    created = 0
    for trade in trades:
        if trade.needs_review or trade.filed_date < cutoff:
            continue
        for user in _watchers(db, trade):
            if db.scalar(select(Alert.id).where(Alert.user_id == user.id, Alert.trade_id == trade.id)) is None:
                db.add(Alert(user_id=user.id, trade_id=trade.id))
                created += 1
    db.commit()
    return created


def send_pending_alerts(db: Session, telegram: TelegramClient) -> DispatchResult:
    """Send queued alerts, and retry recent failures a few times."""
    result = DispatchResult()
    since = utcnow() - timedelta(days=ALERT_MAX_AGE_DAYS)
    queue = db.scalars(
        select(Alert).where(
            Alert.status.in_([ALERT_PENDING, ALERT_FAILED]),
            Alert.attempts < MAX_SEND_ATTEMPTS,
            Alert.created_at >= since,
        ).order_by(Alert.id)
    ).all()
    for alert in queue:
        if alert.user.telegram_status != TELEGRAM_CONNECTED:
            continue
        alert.attempts += 1
        try:
            telegram.send_message(alert.user.telegram_id, format_trade_message(alert.trade))
        except TelegramSendError as exc:
            alert.status = ALERT_FAILED
            alert.error = exc.message[:256]
            if exc.blocked:
                alert.user.telegram_status = TELEGRAM_BLOCKED
                alert.attempts = MAX_SEND_ATTEMPTS
            result.failed += 1
        else:
            alert.status = ALERT_SENT
            alert.error = None
            alert.sent_at = utcnow()
            result.sent += 1
        db.commit()
    return result
