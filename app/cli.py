import argparse
import logging
import sys

from .config import get_settings
from .db import get_sessionmaker
from .ingest import DEFAULT_LOOKBACK_DAYS
from .jobs import market_today, run_daily
from .refdata.load import ReferenceDataError, load_reference_data
from .sec import EdgarClient, EdgarError
from .telegram import TelegramClient


def cmd_load_refdata(_: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        try:
            results = load_reference_data(db)
        except ReferenceDataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    for name, result in results.items():
        print(f"{name}: {result}")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        edgar = EdgarClient(settings.sec_user_agent)
    except EdgarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with get_sessionmaker()() as db:
        report = run_daily(
            db, edgar, TelegramClient(settings.telegram_bot_token), market_today(),
            refresh_refdata=not args.skip_refdata, send_alerts=not args.no_alerts, lookback=args.days,
        )
    for line in report.lines():
        print(line)
    return 1 if report.errors else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("load-refdata", help="Download and sync the S&P 500 and Congress member lists").set_defaults(func=cmd_load_refdata)

    daily = commands.add_parser("daily", help="Refresh lists, ingest new Form 4 filings, and send alerts")
    daily.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="How many past days to check (default %(default)s)")
    daily.add_argument("--no-alerts", action="store_true", help="Ingest filings without sending alerts (backfill)")
    daily.add_argument("--skip-refdata", action="store_true", help="Don't refresh the S&P 500 and Congress lists")
    daily.set_defaults(func=cmd_daily)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
