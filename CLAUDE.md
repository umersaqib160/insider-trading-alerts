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
- Done: the product foundation, plus **strategy step 1, the Filing Scout**, which was tested on a real week of SEC data. A one-quarter scoring backtest is also done (see the next task).
- Review page of last week's top 10: https://claude.ai/artifact/QJQUsi7rUM7DDFXuHTkcMQ

## ▶ NEXT TASK: multi-year scoring backtest, then retune the notable score
Background: the owner proposed extra points for S&P 500 *buys* by size rank, and we agreed on a stricter
cluster rule. Before building either, the owner asked to test the scoring against real price moves. A
one-quarter test (Q1 2026, see `docs/backtest-2026q1.md`) found that the **current score picks worse
trades than average**. Only buys at the top-200 S&P companies beat their benchmark, and directors beat
CEOs. One quarter isn't enough to decide, so the plan is:

1. **Run the backtest over 12 quarters (2023 Q1 – 2025 Q4) plus 2026 Q1**, following `scripts/backtest/README.md`.
   Each quarter needs 6 months of prices afterwards, so all of these qualify. Notes:
   - Run one quarter at a time, and run long downloads in the background; a single command can't run longer than 10 minutes, so re-run the price script until it finishes (it resumes).
   - The scripts use *today's* list of listed companies, so stocks that were delisted since are missing (survivorship bias); mention this.
   - Pool all quarters and also show each quarter on its own, so we can see which signals are stable.
2. **Questions to answer:**
   - Does each scoring signal help, hurt, or do nothing? The signals are size buckets, buy vs sell, role (CEO/CFO/Chair vs other officers vs directors vs 10% owners), the old and new cluster rules, and pre-planned vs unplanned sales.
   - Do the S&P tiers work? Test rank 1–100, 101–200 and 201–500 separately.
   - Does a higher score mean better trades, i.e. do higher score buckets show better outcomes?
3. **Propose new weights** backed by the results, as a short table plus a page for the owner. The likely direction:
   - Raise the bonus for the top-200 S&P companies; possibly drop the 201–500 tier.
   - Soften the CEO points and the size points.
   - Adopt the new cluster rule: only officers and directors count, each buy must be $10K+, and the bonus is tiered by combined value (under $250K: none; $250K–$1M: +15; $1M+: +25).
4. **Get the owner's approval first.** Then implement in `app/agents/scout/scoring.py`, update the tests, re-score, update the README's score table, and commit.
   - The S&P size rank comes from the order of SEC's `company_tickers_exchange.json` (already checked: it follows market value). Store that rank on `companies` in the nightly sync.
   - Apply the S&P bonus to insider **buys only**, not sells and not Congress trades. Both were agreed with the owner.

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
