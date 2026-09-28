import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .alerts import DispatchResult, create_alerts, send_pending_alerts
from .ingest import DEFAULT_LOOKBACK_DAYS, DayResult, days_to_ingest, ingest_day
from .refdata.load import ReferenceDataError, load_reference_data
from .sec import EdgarClient, EdgarError
from .telegram import TelegramClient

log = logging.getLogger(__name__)
MARKET_TZ = ZoneInfo("America/New_York")


def market_today() -> date:
    return datetime.now(MARKET_TZ).date()


@dataclass
class DailyReport:
    refdata: str = "skipped"
    days: list[DayResult] = field(default_factory=list)
    alerts_created: int = 0
    dispatch: DispatchResult = field(default_factory=DispatchResult)
    errors: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"reference data: {self.refdata}"]
        for d in self.days:
            status = f"{d.filings} tracked filings, {len(d.trades)} buys/sells" if d.published else "no index published"
            out.append(f"{d.day}: {status}")
        if not self.days:
            out.append("filings: nothing new to process")
        out.append(f"alerts: {self.alerts_created} queued, {self.dispatch.sent} sent, {self.dispatch.failed} failed")
        out.extend(f"error: {e}" for e in self.errors)
        return out


def run_daily(
    db: Session,
    edgar: EdgarClient,
    telegram: TelegramClient,
    today: date,
    *,
    refresh_refdata: bool = True,
    send_alerts: bool = True,
    lookback: int = DEFAULT_LOOKBACK_DAYS,
) -> DailyReport:
    report = DailyReport()

    if refresh_refdata:
        try:
            results = load_reference_data(db)
            report.refdata = "; ".join(f"{k} {v}" for k, v in results.items())
        except ReferenceDataError as exc:
            # Yesterday's lists are still good enough to match filings against.
            db.rollback()
            report.refdata = "failed"
            report.errors.append(str(exc))

    new_trades = []
    for day in days_to_ingest(db, today, lookback):
        try:
            result = ingest_day(db, edgar, day, today)
        except EdgarError as exc:
            db.rollback()
            report.errors.append(str(exc))
            break  # later days would hit the same outage; the next run retries them
        report.days.append(result)
        new_trades.extend(result.trades)

    if send_alerts:
        report.alerts_created = create_alerts(db, new_trades, today)
    report.dispatch = send_pending_alerts(db, telegram) if send_alerts else DispatchResult()
    return report
