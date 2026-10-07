"""Filing Scout: pulls new insider and Congress trades, scores them, and alerts watchers.

`run_scout` runs every 10 minutes (SEC live feed + Quiver). `run_nightly`
refreshes reference data and re-reads SEC's end-of-day index to catch
anything the live feed missed.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...alerts import DispatchResult, create_alerts, send_pending_alerts
from ...models import Company, Politician, Trade, utcnow
from ...refdata.load import ReferenceDataError, fill_industries, load_reference_data
from ...sec import EdgarClient, EdgarError
from ...telegram import TelegramClient
from .congress import QuiverClient, QuiverError, ingest_congress
from .insiders import ingest_live_feed, prune_processed, recent_business_days, reconcile_days
from .scoring import REVIEW_APPROVED, score_trades

NIGHTLY_RECONCILE_DAYS = 3
NIGHTLY_INDUSTRY_LOOKUPS = 1000
LEFTOVER_DAYS = 3


@dataclass
class ScoutReport:
    lines_: list[str] = field(default_factory=list)
    new_trades: list[Trade] = field(default_factory=list)
    alerts_created: int = 0
    dispatch: DispatchResult = field(default_factory=DispatchResult)
    errors: list[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.lines_.append(line)

    def lines(self) -> list[str]:
        held = sum(1 for t in self.new_trades if t.needs_review)
        return self.lines_ + [
            f"new trades: {len(self.new_trades)} ({held} held for review)",
            f"alerts: {self.alerts_created} queued, {self.dispatch.sent} sent, {self.dispatch.failed} failed",
        ] + [f"error: {e}" for e in self.errors]


def _companies(db: Session) -> tuple[dict[int, Company], dict[str, Company]]:
    companies = db.scalars(select(Company)).all()
    by_cik = {int(c.cik): c for c in companies if c.cik and c.cik.isdigit()}
    by_ticker = {}
    for c in companies:
        for ticker in c.other_tickers or []:
            by_ticker.setdefault(ticker, c)
    by_ticker.update({c.ticker: c for c in companies})
    return by_cik, by_ticker


def _congress(db: Session, quiver: QuiverClient | None, by_ticker: dict[str, Company], report: ScoutReport) -> None:
    if quiver is None:
        report.note("congress: skipped (QUIVER_API_KEY not set)")
        return
    try:
        trades = ingest_congress(db, quiver, by_ticker, db.scalars(select(Politician)).all())
    except QuiverError as exc:
        db.rollback()
        report.errors.append(str(exc))
        return
    report.note(f"congress: {len(trades)} new trades")
    report.new_trades.extend(trades)


def _leftovers(db: Session, report: ScoutReport) -> list[Trade]:
    """Trades an interrupted earlier run stored but never scored or alerted (every scored trade has tags)."""
    since = utcnow() - timedelta(days=LEFTOVER_DAYS)
    seen = {id(t) for t in report.new_trades}
    return [t for t in db.scalars(select(Trade).where(Trade.score == 0, Trade.created_at >= since))
            if not t.tags and id(t) not in seen]


def _finish(db: Session, telegram: TelegramClient, report: ScoutReport, today: date, send_alerts: bool) -> ScoutReport:
    leftovers = _leftovers(db, report)
    if leftovers:
        report.note(f"picked up {len(leftovers)} trades left unscored by an interrupted run")
    todo = report.new_trades + leftovers
    score_trades(db, todo)
    if send_alerts:
        report.alerts_created = create_alerts(db, todo, today)
        report.dispatch = send_pending_alerts(db, telegram)
    return report


def run_scout(
    db: Session, edgar: EdgarClient, quiver: QuiverClient | None, telegram: TelegramClient, today: date,
    *, send_alerts: bool = True,
) -> ScoutReport:
    report = ScoutReport()
    by_cik, by_ticker = _companies(db)
    insiders = ingest_live_feed(db, edgar, by_cik)
    report.note(f"insiders: {insiders.filings} new filings, {len(insiders.trades)} buys/sells")
    report.new_trades.extend(insiders.trades)
    if insiders.error:
        report.errors.append(insiders.error)
    _congress(db, quiver, by_ticker, report)
    return _finish(db, telegram, report, today, send_alerts)


def run_nightly(
    db: Session, edgar: EdgarClient, quiver: QuiverClient | None, telegram: TelegramClient, today: date,
    *, send_alerts: bool = True, refresh_refdata: bool = True, reconcile: int = NIGHTLY_RECONCILE_DAYS,
    industry_lookups: int = NIGHTLY_INDUSTRY_LOOKUPS,
) -> ScoutReport:
    report = ScoutReport()
    if refresh_refdata:
        try:
            results = load_reference_data(db, edgar)
            report.note("reference data: " + "; ".join(f"{k} {v}" for k, v in results.items()))
        except ReferenceDataError as exc:
            db.rollback()
            report.errors.append(str(exc))  # yesterday's lists still work for matching
        try:
            report.note(f"industries: {fill_industries(db, edgar, industry_lookups)} companies looked up")
        except EdgarError as exc:
            db.rollback()
            report.errors.append(str(exc))

    by_cik, by_ticker = _companies(db)
    insiders = reconcile_days(db, edgar, by_cik, recent_business_days(today, reconcile))
    missing = ", ".join(d.isoformat() for d in insiders.unpublished_days)
    report.note(f"insiders: {insiders.filings} filings caught up, {len(insiders.trades)} buys/sells"
                + (f" (no index yet for {missing})" if missing else ""))
    report.new_trades.extend(insiders.trades)
    if insiders.error:
        report.errors.append(insiders.error)
    _congress(db, quiver, by_ticker, report)
    report.note(f"housekeeping: {prune_processed(db, today)} old filing records removed")
    return _finish(db, telegram, report, today, send_alerts)


def approve_trade(db: Session, trade: Trade, telegram: TelegramClient, today: date) -> DispatchResult:
    """Release a trade that was held for review, and alert its watchers."""
    trade.needs_review = False
    trade.review_reason = REVIEW_APPROVED
    db.commit()
    create_alerts(db, [trade], today)
    return send_pending_alerts(db, telegram)
