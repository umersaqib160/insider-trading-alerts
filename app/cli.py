import argparse
import logging
import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.scout import approve_trade, run_nightly, run_scout
from .agents.scout.congress import QuiverClient
from .agents.scout.scoring import NOTABLE_THRESHOLD, load_watchlist, on_watchlist
from .alerts import value_label
from .config import get_settings
from .db import get_sessionmaker
from .formatting import market_today, short_date
from .models import Politician, Trade
from .refdata.load import ReferenceDataError, fill_industries, load_reference_data
from .sec import EdgarClient, EdgarError
from .telegram import TelegramClient


def _edgar() -> EdgarClient:
    return EdgarClient(get_settings().sec_user_agent)


def _quiver() -> QuiverClient | None:
    key = get_settings().quiver_api_key
    return QuiverClient(key) if key else None


def _telegram() -> TelegramClient:
    return TelegramClient(get_settings().telegram_bot_token)


def _session() -> Session:
    return get_sessionmaker()()


def cmd_load_refdata(_: argparse.Namespace) -> int:
    with _session() as db:
        try:
            results = load_reference_data(db, _edgar())
        except ReferenceDataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    for name, result in results.items():
        print(f"{name}: {result}")
    return 0


def cmd_load_industries(args: argparse.Namespace) -> int:
    with _session() as db:
        print(f"{fill_industries(db, _edgar(), args.limit)} companies looked up")
    return 0


def _print_report(report) -> int:
    for line in report.lines():
        print(line)
    return 1 if report.errors else 0


def cmd_scout(args: argparse.Namespace) -> int:
    with _session() as db:
        report = run_scout(db, _edgar(), _quiver(), _telegram(), market_today(), send_alerts=not args.no_alerts)
    return _print_report(report)


def cmd_nightly(args: argparse.Namespace) -> int:
    with _session() as db:
        report = run_nightly(
            db, _edgar(), _quiver(), _telegram(), market_today(),
            send_alerts=not args.no_alerts, refresh_refdata=not args.skip_refdata, reconcile=args.days,
        )
    return _print_report(report)


def _trade_line(rank: int, t: Trade) -> list[str]:
    who = t.actor_name + (f" ({t.actor_role})" if t.actor_role else "")
    hold = "  [HELD: " + t.review_reason + "]" if t.needs_review else ""
    reasons = ", ".join(f"{tag['label']} +{tag['points']}" for tag in t.tags if tag["points"])
    return [
        f"{rank:>2}. {t.score:>3}  {'BUY ' if t.is_buy else 'SELL'} {t.ticker or '—':<6} {value_label(t):<22} "
        f"filed {short_date(t.filed_date):<7} {who}{hold}",
        f"           {reasons}",
    ]


def cmd_top(args: argparse.Namespace) -> int:
    since = market_today() - timedelta(days=args.days)
    with _session() as db:
        stmt = select(Trade).where(Trade.filed_date >= since)
        if not args.include_held:
            stmt = stmt.where(Trade.needs_review.is_(False))
        if args.source == "insiders":
            stmt = stmt.where(Trade.source == "sec_form4")
        elif args.source == "congress":
            stmt = stmt.where(Trade.source != "sec_form4")
        trades = db.scalars(stmt.order_by(Trade.score.desc(), Trade.value_low.desc(), Trade.id).limit(args.limit)).all()
        if not trades:
            print(f"No trades filed since {since} yet.")
            return 0
        print(f"Top {len(trades)} trades filed since {since} (notable = {NOTABLE_THRESHOLD}+; "
              f"{'including' if args.include_held else 'excluding'} trades held for review):\n")
        for i, trade in enumerate(trades, 1):
            print("\n".join(_trade_line(i, trade)))
    return 0


def cmd_review(_: argparse.Namespace) -> int:
    with _session() as db:
        held = db.scalars(select(Trade).where(Trade.needs_review.is_(True)).order_by(Trade.filed_date.desc())).all()
        if not held:
            print("Nothing is waiting for review.")
        for t in held:
            print(f"#{t.id}  {t.ticker or '—'}  {value_label(t)}  {t.actor_name}  — {t.review_reason}\n      {t.source_url}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    with _session() as db:
        trade = db.get(Trade, args.trade_id)
        if trade is None or not trade.needs_review:
            print(f"error: trade #{args.trade_id} isn't waiting for review", file=sys.stderr)
            return 1
        result = approve_trade(db, trade, _telegram(), market_today())
    print(f"Released trade #{args.trade_id}: {result.sent} alerts sent, {result.failed} failed")
    return 0


def cmd_watchlist(_: argparse.Namespace) -> int:
    names = load_watchlist()
    with _session() as db:
        politicians = db.scalars(select(Politician).where(Politician.active.is_(True))).all()
    matched = {n for n in names for p in politicians if on_watchlist(p, {n})}
    for name in sorted(names):
        print(f"{'✓' if name in matched else '✗ no current member named'} {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("load-refdata", help="Sync listed companies, the S&P 500 and Congress members").set_defaults(func=cmd_load_refdata)
    industries = commands.add_parser("load-industries", help="Look up SEC industry codes for companies (one request each)")
    industries.add_argument("--limit", type=int, default=7000)
    industries.set_defaults(func=cmd_load_industries)

    scout = commands.add_parser("scout", help="Every 10 minutes: new Form 4s and Congress trades, scored and alerted")
    scout.add_argument("--no-alerts", action="store_true", help="Store and score without sending alerts")
    scout.set_defaults(func=cmd_scout)

    nightly = commands.add_parser("nightly", help="Refresh lists and catch up on anything the live feed missed")
    nightly.add_argument("--days", type=int, default=3, help="Business days of SEC index to re-check (default %(default)s)")
    nightly.add_argument("--no-alerts", action="store_true", help="Backfill without sending alerts")
    nightly.add_argument("--skip-refdata", action="store_true", help="Don't refresh company and Congress lists")
    nightly.set_defaults(func=cmd_nightly)

    top = commands.add_parser("top", help="The most notable recent trades, with their score and reasons")
    top.add_argument("--days", type=int, default=7)
    top.add_argument("--limit", type=int, default=10)
    top.add_argument("--source", choices=["all", "insiders", "congress"], default="all")
    top.add_argument("--include-held", action="store_true", help="Include trades held for review")
    top.set_defaults(func=cmd_top)

    commands.add_parser("review", help="Trades held back for a human check").set_defaults(func=cmd_review)
    approve = commands.add_parser("approve", help="Release a held trade and send its alerts")
    approve.add_argument("trade_id", type=int)
    approve.set_defaults(func=cmd_approve)
    commands.add_parser("watchlist", help="Check which high-profile names match current members").set_defaults(func=cmd_watchlist)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EdgarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
