"""Owner warnings when a scheduled job has problems."""

from datetime import datetime, timedelta, timezone

from app.models import JobStatus
from app.monitoring import (
    JOB_NIGHTLY, JOB_SCOUT, MISSED_FILINGS_WARNING, missed_filings_warning, report_run, stale_job_warning,
)
from app.telegram import TelegramSendError

OWNER = 4242
T0 = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_clean_runs_send_nothing(db, telegram):
    assert report_run(db, telegram, OWNER, JOB_SCOUT, [], now=T0) is False
    assert telegram.sent == []
    assert db.get(JobStatus, JOB_SCOUT).last_ok_at is not None


def test_scout_warns_after_two_bad_runs_then_reminds_and_recovers(db, telegram):
    report_run(db, telegram, OWNER, JOB_SCOUT, ["SEC EDGAR returned HTTP 503"], now=at(0))
    assert telegram.sent == []  # one blip fixes itself on the next run
    report_run(db, telegram, OWNER, JOB_SCOUT, ["SEC EDGAR returned HTTP 503 for <feed>"], now=at(10))
    chat, text = telegram.sent[0]
    assert chat == OWNER
    assert text.splitlines()[0] == "⚠️ <b>Behind The Curtain: problem in the 10-minute job</b>"
    assert "• SEC EDGAR returned HTTP 503 for &lt;feed&gt;" in text  # filing and error text is escaped

    for minutes in range(20, 360, 10):  # still failing: no more messages for 6 hours
        report_run(db, telegram, OWNER, JOB_SCOUT, ["still down"], now=at(minutes))
    assert len(telegram.sent) == 1
    report_run(db, telegram, OWNER, JOB_SCOUT, ["still down"], now=at(370))
    assert len(telegram.sent) == 2

    report_run(db, telegram, OWNER, JOB_SCOUT, [], now=at(380))
    assert telegram.sent[-1][1] == "✅ <b>Behind The Curtain: the 10-minute job is working again.</b>"
    report_run(db, telegram, OWNER, JOB_SCOUT, [], now=at(390))
    assert len(telegram.sent) == 3  # recovery is announced once


def test_a_single_blip_is_never_reported(db, telegram):
    report_run(db, telegram, OWNER, JOB_SCOUT, ["blip"], now=at(0))
    report_run(db, telegram, OWNER, JOB_SCOUT, [], now=at(10))
    report_run(db, telegram, OWNER, JOB_SCOUT, ["another blip"], now=at(20))
    assert telegram.sent == []


def test_nightly_warns_on_its_first_failure(db, telegram):
    assert report_run(db, telegram, OWNER, JOB_NIGHTLY, ["S&P 500 list has only 3 companies; refusing to sync."], now=T0)
    assert "problem in the nightly job" in telegram.sent[0][1]


def test_no_owner_configured_or_telegram_down_never_breaks_the_job(db, telegram):
    assert report_run(db, telegram, None, JOB_NIGHTLY, ["boom"], now=at(0)) is False
    telegram.error = TelegramSendError("Couldn't reach Telegram. Try again in a minute.")
    assert report_run(db, telegram, OWNER, JOB_NIGHTLY, ["boom"], now=at(10)) is False
    telegram.error = None
    assert report_run(db, telegram, OWNER, JOB_NIGHTLY, ["boom"], now=at(20)) is True  # sent as soon as it can be


def test_jobs_watch_each_other(db, telegram):
    assert stale_job_warning(db, JOB_NIGHTLY, now=T0) is None  # never ran: nothing to compare with
    report_run(db, telegram, OWNER, JOB_NIGHTLY, [], now=T0)
    assert stale_job_warning(db, JOB_NIGHTLY, now=T0 + timedelta(hours=25)) is None
    assert stale_job_warning(db, JOB_NIGHTLY, now=T0 + timedelta(hours=30)) == \
        "The nightly job hasn't finished a clean run for 30 hours."

    report_run(db, telegram, OWNER, JOB_SCOUT, [], now=T0)
    report_run(db, telegram, OWNER, JOB_SCOUT, ["down"], now=at(90))  # a failed run doesn't count as clean
    assert stale_job_warning(db, JOB_SCOUT, now=at(95)) == "The 10-minute job hasn't finished a clean run for 95 minutes."


def test_warnings_are_reported_but_the_run_still_counts_as_clean(db, telegram):
    warning = missed_filings_warning(MISSED_FILINGS_WARNING + 15)
    assert missed_filings_warning(3) is None and "found 40 filings the 10-minute job missed" in warning
    assert report_run(db, telegram, OWNER, JOB_NIGHTLY, [], [warning], now=T0)
    assert db.get(JobStatus, JOB_NIGHTLY).last_ok_at is not None
