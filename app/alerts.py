from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .formatting import money, shares, short_date
from .models import (
    ALERT_FAILED, ALERT_PENDING, ALERT_SENT, TELEGRAM_BLOCKED, TELEGRAM_CONNECTED,
    Alert, CompanyWatch, Trade, User, utcnow,
)
from .telegram import TelegramClient, TelegramSendError

# Trades filed longer ago than this are history, not news: store them but don't alert.
ALERT_MAX_AGE_DAYS = 7
MAX_SEND_ATTEMPTS = 3


@dataclass
class DispatchResult:
    created: int = 0
    sent: int = 0
    failed: int = 0


def format_trade_message(trade: Trade) -> str:
    buy = trade.is_buy
    company = trade.company.name if trade.company else trade.ticker
    who = f"{trade.insider_name} ({trade.insider_title})" if trade.insider_title else trade.insider_name
    action = f"{'bought' if buy else 'sold'} {shares(trade.shares)} shares"
    if trade.avg_price:
        action += f" (avg ${trade.avg_price:,.2f})"
    lines = [
        f"<b>{'BUY' if buy else 'SELL'} · {escape(trade.ticker)}</b> ({escape(company)})",
        f"{escape(who)} {action}",
    ]
    if trade.value:
        lines.append(f"Value: {money(trade.value)}")
    lines.append(f"Traded {short_date(trade.trade_date)} · Filed {short_date(trade.filed_date)}")
    if trade.is_10b5_1:
        lines.append("Pre-planned under a Rule 10b5-1 trading plan")
    lines.append(f'<a href="{escape(trade.source_url)}">View the Form 4 on SEC EDGAR</a>')
    return "\n".join(lines)


def create_alerts(db: Session, trades: list[Trade], today: date) -> int:
    """Queue one alert per connected user watching each recent trade's company."""
    cutoff = today - timedelta(days=ALERT_MAX_AGE_DAYS)
    created = 0
    for trade in trades:
        if trade.company_id is None or trade.filed_date < cutoff:
            continue
        watchers = db.scalars(
            select(User).join(CompanyWatch, CompanyWatch.user_id == User.id)
            .where(CompanyWatch.company_id == trade.company_id, User.telegram_status == TELEGRAM_CONNECTED)
        )
        for user in watchers:
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
