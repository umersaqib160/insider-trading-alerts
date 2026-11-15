"""Warns the owner on Telegram when a scheduled job has problems, so alerts never stop silently.

Each job (the 10-minute scout, the nightly catch-up) records its runs in `job_status`. Problems send
the owner one message (for the scout only after two bad runs in a row, since a single blip fixes itself
on the next run), a reminder every 6 hours while they last, and one more when the job is healthy again. The two jobs also watch each other: each warns if the other has
not finished a clean run for too long, which covers a job that has stopped running altogether.
"""

from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy.orm import Session

from .models import JobStatus, utcnow
from .telegram import TelegramClient, TelegramSendError

JOB_SCOUT = "scout"
JOB_NIGHTLY = "nightly"
JOB_LABELS = {JOB_SCOUT: "10-minute job", JOB_NIGHTLY: "nightly job"}
# How long each job may go without a clean run before the other one warns about it.
STALE_AFTER = {JOB_SCOUT: timedelta(hours=1), JOB_NIGHTLY: timedelta(hours=26)}
NOTIFY_EVERY = timedelta(hours=6)
# Bad runs in a row before the first warning. The scout runs every 10 minutes and re-reads the last hour of
# filings, so one failed run loses nothing; the nightly job runs once a day, so one failure matters.
WARN_AFTER_RUNS = {JOB_SCOUT: 2, JOB_NIGHTLY: 1}
# The nightly catch-up normally finds next to nothing. This many missed filings means the live feed is failing.
MISSED_FILINGS_WARNING = 25


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back datetimes without a timezone; everything stored here is UTC."""
    return moment.replace(tzinfo=timezone.utc) if moment is not None and moment.tzinfo is None else moment


def _ago(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{hours:.0f} hours" if hours >= 2 else f"{delta.total_seconds() / 60:.0f} minutes"


def stale_job_warning(db: Session, job: str, now: datetime | None = None) -> str | None:
    """A warning if `job` has run before but hasn't finished a clean run recently."""
    now = now or utcnow()
    status = db.get(JobStatus, job)
    last_ok = _aware(status.last_ok_at) if status else None
    if last_ok is None or now - last_ok <= STALE_AFTER[job]:
        return None
    return f"The {JOB_LABELS[job]} hasn't finished a clean run for {_ago(now - last_ok)}."


def missed_filings_warning(caught_up: int) -> str | None:
    if caught_up < MISSED_FILINGS_WARNING:
        return None
    return (f"The nightly catch-up found {caught_up} filings the 10-minute job missed, "
            "so alerts for those went out late.")


def _message(job: str, problems: list[str]) -> str:
    lines = [f"⚠️ <b>Behind The Curtain: problem in the {JOB_LABELS[job]}</b>"]
    lines += [f"• {escape(p[:300])}" for p in problems[:5]]
    if len(problems) > 5:
        lines.append(f"…and {len(problems) - 5} more.")
    lines.append("")
    lines.append("You'll get a reminder every 6 hours while this lasts, and a message when it's fixed.")
    return "\n".join(lines)


def report_run(
    db: Session, telegram: TelegramClient, owner_id: int | None, job: str,
    errors: list[str], warnings: list[str] | None = None, now: datetime | None = None,
) -> bool:
    """Record a finished run and tell the owner about new problems or a recovery. True if a message was sent."""
    now = now or utcnow()
    problems = list(errors) + list(warnings or [])
    status = db.get(JobStatus, job)
    if status is None:
        status = JobStatus(name=job)
        db.add(status)
    status.last_run_at = now
    if not errors:
        status.last_ok_at = now  # warnings are about something else (the other job, late alerts), not this run
    status.last_problem = "; ".join(problems)[:1000] or None
    status.problem_runs = (status.problem_runs or 0) + 1 if problems else 0

    text = None
    last_notified = _aware(status.last_notified_at)
    due = not status.alerting or last_notified is None or now - last_notified >= NOTIFY_EVERY
    if problems and status.problem_runs >= WARN_AFTER_RUNS[job] and due:
        text = _message(job, problems)
    elif not problems and status.alerting:
        text = f"✅ <b>Behind The Curtain: the {JOB_LABELS[job]} is working again.</b>"

    sent = False
    if text and owner_id:
        try:
            telegram.send_message(owner_id, text)
            sent = True
        except TelegramSendError:
            pass  # the warning must never break the job itself; it is retried on the next run
    if sent:
        status.alerting = bool(problems)
        status.last_notified_at = now
    db.commit()
    return sent
