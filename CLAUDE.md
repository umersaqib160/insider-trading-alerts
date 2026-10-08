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
- Done: the product foundation, plus **strategy step 1, the Filing Scout**, which was tested on a real week of SEC data. A 13-quarter scoring backtest is also done (see the next task).
- Review page of last week's top 10: https://claude.ai/artifact/QJQUsi7rUM7DDFXuHTkcMQ

## ▶ NEXT TASK: owner approval of new notable-score weights, then implement
The 13-quarter backtest (2023 Q1 – 2026 Q1) is done: `docs/backtest-2023-2026.md`, owner page
https://claude.ai/artifact/JMS1ZfwhBrTiKHPcdGKktA. Findings: today's score runs backwards (notable buys rose 54% vs 57%
for all buys); size points and CEO points hurt; officers/directors and S&P 500 buys help; clusters (old or new rule)
add nothing; sells predict nothing.

Proposed insider weights (Congress unchanged): buy 30; size 0 (keep the tag as a fact); CEO/CFO/Chair 5; other
officer 20; director 20; 10% owner 0; S&P rank 1–200 +25 and 201–500 +15 (buys only); cluster +5 flat with the new
rule (officers/directors, $10K+ each, $250K+ combined); sales 0 (sells never notable). Result: notable buys rose
65% (62% without hindsight), ~113 notable a quarter. `CANDIDATE` in `scripts/backtest/pool.py` holds these weights.

**Waiting on the owner** for four decisions (on the page): notable becomes mostly S&P 500 buys; fewer notable
trades (~9 a week); flat +5 cluster instead of the agreed +15/+25 tiers; one +25 tier for ranks 1–200.
Once approved: implement in `app/agents/scout/scoring.py`, store the S&P size rank on `companies` in the nightly sync
(order of SEC's `company_tickers_exchange.json`), update the tests, re-score, update the README's score table, commit.

## Open items
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
