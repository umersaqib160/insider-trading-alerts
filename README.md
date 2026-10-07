# Behind The Curtain

A web app where users star the US companies and members of Congress they
care about, and get a Telegram alert whenever one of them files a trade.
Company insider trades come from SEC Form 4 filings; Congress trades come
from House and Senate periodic transaction reports, via the Quiver API.

> **Scope note:** everything comes from legally mandated public filings.
> The app reports what was filed, to everyone the same way, and never tells
> anyone to buy or sell. Every alert carries a "not investment advice" line.

The marketing and automation plan lives in the strategy document
("Behind the Curtain — Marketing & Automation Strategy"). It's being built
one step at a time; see [Roadmap](#roadmap).

## Status

**Built:** Telegram login and test notifications; watchlists over every US
company on Nasdaq, NYSE and Cboe (about 6,100) and all of Congress; and the
**Filing Scout** (strategy step 1), which checks for new trades every 10
minutes, scores them, and alerts watchers.

**Waiting on you:** a Quiver API key (Congress trades), the Telegram bot
token, and a Railway account to deploy.

## Filing Scout

Code lives in [`app/agents/scout/`](app/agents/scout/).

**Every 10 minutes** (`python -m app.cli scout`):
1. **Company insiders:** reads SEC's live feed of new filings, newest first,
   until it reaches filings it has already read (or an hour of history).
   Each new Form 4 for a listed company is downloaded and its open-market
   purchases (code `P`) and sales (code `S`) are kept. Grants, option
   exercises and tax withholding are skipped. A filing's transaction lines
   are totalled into one trade with an average price, and pre-planned Rule
   10b5-1 trades are flagged.
2. **Congress:** fetches recent House and Senate trades from Quiver,
   matched to members by their Congress ID (or name) and to companies by
   ticker. Exchanges are skipped. Without `QUIVER_API_KEY` this step is
   skipped and the run says so.
3. **Scores** new trades (below), and re-scores older trades whose cluster
   counts changed.
4. **Alerts** every connected user who starred the company or the
   politician. One Telegram message per trade; failed sends retry up to 3
   times; trades filed more than 7 days ago are stored but not alerted.

**Every night** (`python -m app.cli nightly`): refreshes the company and
Congress lists, looks up industry codes for up to 1,000 companies, re-reads
SEC's end-of-day index for the last 3 business days to catch anything the
live feed missed, and clears out old bookkeeping.

Everything is idempotent: re-running never stores or sends a trade twice.

### The notable score

Each trade gets a 0–100 score from the points below; **60+ is notable**.
The score picks what the marketing agents will talk about. It doesn't
filter anyone's alerts: users get every buy and sell for what they starred.
All weights are in [`scoring.py`](app/agents/scout/scoring.py).

| Signal | Points |
|---|---|
| Size (insiders) | $100K+ 5 · $1M+ 15 · $5M+ 25 · $10M+ 35 |
| Size (Congress, bottom of range) | $15K+ 5 · $50K+ 15 · $250K+ 25 · $1M+ 35 |
| Direction | Insider buy 20 · unplanned sale 5 · pre-planned sale 0 · Congress buy 10, sale 5 |
| Who (insiders) | CEO/CFO/Chair 20 · other officer 10 · director 8 · 10% owner 5 |
| Who (Congress) | High-profile list 20 · committee chair or ranking member 10 |
| Committee link | Member sits on a committee overseeing the company's industry: 15 |
| Cluster | 3+ insiders buying the same company within 14 days: 25 · 2+ members trading the same stock within 14 days: 15 |

The reasons behind each score are stored as tags. Factual ones ("CEO",
"$5M+", "Sits on Armed Services") are shown to users on trades and in
alerts; the number itself and the high-profile list stay internal. Edit the
high-profile list in
[`app/data/watchlist_politicians.txt`](app/data/watchlist_politicians.txt)
and check which names match with `python -m app.cli watchlist`.

**Held for review:** trades over $50M, or with values that look wrong
(trade date after filing, a year-old trade, an impossible share price), are
stored but not alerted. List them with `python -m app.cli review` and
release one with `python -m app.cli approve <id>`.

**Weekly hand check:** `python -m app.cli top --days 7` lists the top trades
with their points, so the weights can be tuned.

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                  # then set SEC_USER_AGENT
.venv/bin/alembic upgrade head        # creates dev.db (SQLite)
.venv/bin/python -m app.cli load-refdata          # companies + Congress (seconds)
.venv/bin/python -m app.cli load-industries       # optional: sectors for all companies (~15 min)
.venv/bin/python -m app.cli nightly --no-alerts --skip-refdata --days 7   # backfill a week
.venv/bin/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and use **Dev login**. Telegram's login widget
only works on the domain registered with @BotFather, so it can't run on
localhost. To get real alerts locally, set `TELEGRAM_BOT_TOKEN` and set
`DEV_TELEGRAM_ID` to your own Telegram user id (press Start in your chat
with the bot first).

Run the tests with `.venv/bin/pytest`.

## Deploying to Railway

1. Create a Railway project from this GitHub repo and add a **Postgres**
   database. Railway sets `DATABASE_URL`.
2. Set these variables on the web service:
   - `APP_ENV=production`
   - `SECRET_KEY`: a long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` (without the `@`)
   - `SEC_USER_AGENT`, e.g. `Behind The Curtain you@example.com` (SEC
     requires a real contact email)
   - `QUIVER_API_KEY`
3. Deploy. The `Procfile` runs migrations, then starts the app. `/healthz`
   is the health check.
4. Generate a public domain. In @BotFather, send `/setdomain`, pick the bot,
   and enter that domain so the login widget works.
5. Add two cron services from the same repo, with the same variables
   (reference `DATABASE_URL` from Postgres):
   - **Scout:** start command `python -m app.cli scout`, schedule `*/10 * * * *`
   - **Nightly:** start command `python -m app.cli nightly`, schedule `0 7 * * *`
     (07:00 UTC, after SEC publishes the previous day's index)

   Before turning the crons on, run `python -m app.cli load-refdata`,
   `python -m app.cli load-industries` and
   `python -m app.cli nightly --no-alerts --days 7` once from a Railway
   shell, so the first scheduled run doesn't alert on a week of history.

## Data sources

| Data | Source | Cost |
|---|---|---|
| Company insider trades | SEC EDGAR live feed + daily index (Form 4) | Free; needs `SEC_USER_AGENT` |
| Congress trades | Quiver API, live congress trading endpoint | Paid; `QUIVER_API_KEY` |
| Listed US companies | SEC `company_tickers_exchange.json` (Nasdaq, NYSE, Cboe; OTC excluded) | Free |
| Sectors and industries | S&P 500 members: official GICS from the [S&P 500 dataset](https://github.com/datasets/s-and-p-500-companies). Everyone else: SEC industry (SIC) codes mapped to the closest sector | Free |
| Members of Congress | [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators): members, committees, chairs | Free |

**Licensing to check before launch:** that your Quiver plan allows
commercial use and showing the data publicly; and, with a lawyer, how the
Ethics in Government Act's limits on commercial use of congressional
reports apply.

## Data model

```
users                  Telegram identity and connection status
companies              one row per SEC CIK: ticker (+ other share classes), exchange,
                       sector, industry, SIC code, S&P 500 flag
politicians            current members, committees, committees they lead
company_watches        a user's starred companies
politician_watches     a user's starred politicians
trades                 shared fields for every trade: source, who, ticker, buy/sell,
                       value low/high, trade and filed dates, score, tags, review hold
insider_trade_details  Form 4 only: accession, shares, average price, 10b5-1 flag
congress_trade_details House/Senate only: chamber, owner, amount range, description
processed_filings      Form 4s already read, so none is fetched twice
alerts                 one per user per trade; doubles as the no-duplicates record
```

## Tech stack

Python · FastAPI + Jinja + HTMX · SQLAlchemy + Alembic · Postgres on Railway
(SQLite locally) · Telegram Bot API · httpx.

## Brand

- **Name:** Behind The Curtain
- **Palette:** `#000000` · `#2A0048` · `#560072` · `#800080` · `#A90072` ·
  `#D50048` · `#FF0000`
- **Themes:** light, dark, or match the device.
- **Semantic colors stay separate from the brand:** buys are green, sells
  red.
- **UI prototype:** [`prototype/index.html`](prototype/index.html), with example data.

## Roadmap

Product foundations (done): Telegram login, watchlists, company pages,
alert history, light and dark themes.

Strategy build order:
- [x] **1. Filing Scout:** SEC Form 4 + Quiver Congress trades, notable
      score, review hold, alerts for starred companies and politicians.
- [ ] **2. Onboarding Agent:** merchant-of-record checkout and webhooks;
      Pro on/off; Skool invite.
- [ ] **3. Content Agent:** X and Reddit drafts from notable trades, via the
      Claude API, waiting for approval.
- [ ] **4. Approval step:** Approve/Skip buttons in a private Telegram chat.
- [ ] **5. Poster Agent:** publishes approved drafts to X with a daily cap.
- [ ] **6. Teaser and Digest Agents:** free Telegram channel, weekly email.
- [ ] **7. Analytics Agent:** weekly numbers report.

Shelved: Reddit/StockTwits rumor signals (they don't fit "report what was
filed").
