# CLAUDE.md: handoff notes for new sessions

Read this first, then `README.md` (architecture, commands, deploy) and
`docs/marketing-strategy.md` (the plan we're building step by step).

## How we work
- Build the strategy **one step at a time**. Show the plan and ask questions before writing code.
- The owner (Umer) prefers plain-language explanations, recommendations with tradeoffs, and short recaps.
- Commit and push to `main` after each verified step. Run `.venv/bin/pytest` (160+ tests) before pushing.
- Never paste secrets in chat; they go in `.env` locally or Railway variables.

## Decisions already made (don't re-ask)
- Name: **Behind The Curtain** (capital T). Palette black→violet→purple→magenta→crimson→red; light and dark themes.
- Stack: Python, FastAPI + Jinja + HTMX, SQLAlchemy + Alembic, Postgres on Railway (SQLite locally).
- Hosting: Railway, with a web service plus two cron services: `scout` every 10 min and `nightly` at 07:00 UTC.
- Sign-in: Log in with Telegram (login widget). Alerts are Telegram messages, one per trade, with emojis and a "not investment advice" line.
- Universe: every US company on Nasdaq, NYSE and Cboe (~6,100), **OTC excluded**; S&P 500 is a filter.
- Trades: only buys and sells (Form 4 codes P and S; Congress purchases and sales, no exchanges).
- Congress data comes from the **Quiver API**, not PDF scraping. Insider data comes from SEC EDGAR (free).
- Trades table design: a shared `trades` table plus `insider_trade_details` and `congress_trade_details`.
- Notable score: an internal 0–100 score (weights in `app/agents/scout/scoring.py`). Users see only the
  factual tags behind it, never the number. Users get every alert for what they starred, whatever the score.
- Hold for review: trades over $50M or with odd values; release with `python -m app.cli approve <id>`.
- Shelved: Reddit/StockTwits rumor signals.

## Status (as of Oct 8, 2026)
- Done: the product foundation, plus **strategy step 1, the Filing Scout**, which was tested on a real week of SEC data.
- Review page of last week's top 10: https://claude.ai/artifact/QJQUsi7rUM7DDFXuHTkcMQ

## Open items
- **Scoring tuning (waiting on owner):** small caps dominate the top 10. Proposed: +10 for S&P 500
  companies ("famous name"), and/or a minimum trade size before the insider-cluster bonus applies.
- **Waiting on owner:** a Quiver API key (also check the plan allows commercial use and public display), the
  Telegram bot token and username, a Railway account, and a real contact email for `SEC_USER_AGENT`.
- **Unverified until the Quiver key arrives:** Quiver field names and auth header (`Authorization: Token <key>`)
  in `app/agents/scout/congress.py`. Check them against a real response.
- **Legal (for a lawyer):** commercial use of congressional reports (Ethics in Government Act); EU/Belgium rules
  on investment recommendations.
- **Next strategy step:** step 2, the Onboarding Agent (merchant-of-record checkout and webhooks, Pro on/off,
  Skool invite). The payment provider needs to approve the product first.

## Gotchas
- SEC throttles bursts (HTTP 429). The client paces requests to about 5 per second and retries; a full-week backfill takes about 15 minutes.
- Funds and their partners co-file identical Form 4s. These are deduplicated by company, date, shares and price.
- `load-industries` makes one SEC request per company (about 15 minutes for all of them); the nightly job does 1,000 per run.
