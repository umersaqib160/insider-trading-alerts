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
- Done: the product foundation, plus **strategy step 1, the Filing Scout**, which was tested on a real week of SEC data, and the backtested notable score (below).
- Review page of last week's top 10: https://claude.ai/artifact/QJQUsi7rUM7DDFXuHTkcMQ

## Notable score (done, Oct 2026)
The 13-quarter backtest (2023 Q1 – 2026 Q1, `docs/backtest-2023-2026.md`, owner page
https://claude.ai/artifact/JMS1ZfwhBrTiKHPcdGKktA) showed the old score ran backwards. The owner approved new
insider weights, now in `app/agents/scout/scoring.py`: buy 30; size 0 (fact tag only); CEO/CFO/Chair 5; other officer
20; director 20; 10% owner 0; S&P 500 buys rank 1–200 +25, 201–500 +15; cluster +5 (3+ officers/directors, $10K+ each,
$250K+ combined); sales 0, so sells are never notable. Congress weights are unchanged (untested; no data yet).
`companies.size_rank` / `sp500_rank` come from the order of SEC's `company_tickers_exchange.json` in the nightly sync.
Expect about 9 notable insider trades a week.

**X posting (decided, build with the Content Agent):** buys only; notable trades, plus "newsworthy" buys
($1M+ by officers/directors, clusters, Congress purchases), plus fact-checked follow-ups ("up 30% since we sent
this"). Rules are in `docs/marketing-strategy.md` under "What the X account posts".

## ▶ NEXT TASK
Strategy step 2, the Onboarding Agent (see Open items), once the payment provider approves the product.

## Open items
- **Waiting on owner:** a Quiver API key (also check the plan allows commercial use and public display), the
  Telegram bot token and username, and a Railway account.
- `SEC_USER_AGENT` is `Behind The Curtain umersaqib160@hotmail.com` (set it as a Railway variable too).
- Checked Oct 18, 2026: the full Scout (migrations 0001–0004, refdata, backfill) runs on Postgres 16, not just SQLite.
- **Unverified until the Quiver key arrives:** Quiver field names and auth header (`Authorization: Token <key>`)
  in `app/agents/scout/congress.py`. Check them against a real response.
- **Legal (for a lawyer):** commercial use of congressional reports (Ethics in Government Act); EU/Belgium rules
  on investment recommendations.
- **Next strategy step:** step 2, the Onboarding Agent (merchant-of-record checkout and webhooks, Pro on/off,
  Skool invite). The payment provider needs to approve the product first.
- **Before the Content Agent:** pick a daily price source for fact-checked follow-up posts and the track record page.

## Gotchas
- SEC answers **403** (not 404) for a daily index that doesn't exist, e.g. on a US holiday. Only the daily-index
  fetch treats 403 as missing; everywhere else 403 is an error (usually a bad `SEC_USER_AGENT`).
- SEC throttles bursts (HTTP 429). The client paces requests to about 5 per second and retries; a full-week backfill takes about 15 minutes.
- Funds and their partners co-file identical Form 4s. These are deduplicated by company, date, shares and price.
- `load-industries` makes one SEC request per company (about 15 minutes for all of them); the nightly job does 1,000 per run.
