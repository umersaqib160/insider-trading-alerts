# Behind The Curtain

A web app where users pick the stocks and US politicians they care about, and
get a Telegram alert whenever one of those company insiders or politicians
discloses a trade.

## Brand

- **Name:** Behind The Curtain
- **Palette:** `#000000` · `#2A0048` · `#560072` · `#800080` · `#A90072` ·
  `#D50048` · `#FF0000` (black → violet → purple → magenta → crimson → red)
- **Themes:** light and dark, plus "match your device". Users switch themes
  in the header or under Settings → Appearance.
- **Semantic colors stay separate from the brand:** buys are green, sells
  are red, and unverified forum signals are amber, so a trade's direction
  never depends on the brand palette.
- **UI prototype:** [`prototype/index.html`](prototype/index.html), a
  clickable mockup that uses example data.

> **Scope note:** Tier 1 signals come only from legally mandated public
> disclosures — SEC Form 4 filings and STOCK Act Periodic Transaction
> Reports. Tier 2 signals come from public web/forum discussion and are
> always labelled as unverified. The app never uses or trades on nonpublic
> information; it is a monitoring/aggregation tool, in the same category as
> Capitol Trades, Quiver Quantitative, or Unusual Whales.

## Status

📋 **Planning stage.** No code yet — this README is the working plan.

## Product overview

Single user (the project owner) at first; built multi-user from day one so
others can sign up later.

**Stocks** — browse/search the S&P 500 (all US-listed stocks later) and star
the ones to watch. When an insider (exec, director, 10%+ owner) at a starred
company files a trade, the user gets an alert.

**Politicians** — browse/search current members of Congress (filter by
chamber, party, state, committee) and star the ones to watch. When a starred
politician files a trade disclosure, the user gets an alert.

**Alerts / Settings** — Telegram connection status, a **"Send test
notification"** button, and a history of alerts already sent.

**Sign-in** — "Log in with Telegram". One click signs the user in *and*
authorizes the bot to message them, so there's no password, no email
provider, and no chat ID to copy/paste.

## Signal sources

### Tier 1: regulatory disclosures (confirmed)

| Source | Who | Filing | Disclosure window | Access |
|---|---|---|---|---|
| SEC Form 4 | Company executives, directors, 10%+ owners | Statement of Changes in Beneficial Ownership | Within 2 business days of trade | SEC EDGAR, free, no key (requires a descriptive `User-Agent`, max 10 req/s) |
| House PTR | US House Representatives | Periodic Transaction Report | Within 45 days of trade | House Clerk's [Financial Disclosure site](https://disclosures-clerk.house.gov/) (PDF-based, needs parsing) |
| Senate PTR | US Senators | Periodic Transaction Report | Within 45 days of trade | Senate [eFD system](https://efdsearch.senate.gov/) (session-based search, needs parsing) |

Community-maintained parsers exist for House/Senate PTR data (e.g. the
House/Senate Stock Watcher projects) — evaluate before parsing PDFs from
scratch.

Senior executive-branch officials (cabinet etc.) file a different form (OGE
278-T) — a possible later addition for "policy-influential" people beyond
Congress.

### Tier 2: unverified web/forum signals

Filings are confirmed but lagging (up to 45 days for politicians). Chatter on
forums and social media sometimes surfaces the same trades earlier — but it's
rumor, not disclosure, so it's stored separately and always labelled as such
in alerts.

- Reddit (official API) — r/wallstreetbets, r/investing, r/SecurityAnalysis
- StockTwits (public API, ticker-tagged posts)
- X/Twitter cashtag search (paid API — evaluate cost first)
- Financial news RSS for "insider buying/selling" coverage

Tier 2 is matched against what users actually watch (starred tickers and
politicians) rather than crawling blindly — keeps noise down. Official APIs
are preferred over HTML scraping (more stable, fewer blocks, no ToS issues).

### Reference data

- **S&P 500 constituents** — list of tickers, refreshed monthly (membership
  changes a few times a year).
- **Ticker ↔ SEC CIK mapping** — SEC's public `company_tickers.json`, needed
  to match Form 4 filings to companies.
- **Members of Congress** — the public-domain
  [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators)
  dataset (names, chamber, party, state, IDs, committees).

## Architecture

Everything runs on **Railway**, deployed from this GitHub repo:

```
 ┌──────────────────────────── Railway project ────────────────────────────┐
 │                                                                          │
 │  ┌────────────────────────┐          ┌──────────────────────────────┐   │
 │  │  Web service            │          │  Daily job (cron service)     │   │
 │  │  FastAPI + HTMX pages   │          │  runs once/day, then exits    │   │
 │  │  - Telegram login       │          │  1. refresh reference data    │   │
 │  │  - Stocks / Politicians │          │  2. ingest Form 4, PTRs,      │   │
 │  │  - star / unstar        │          │     Tier 2 sources            │   │
 │  │  - test notification    │          │  3. match new trades against  │   │
 │  │  - alert history        │          │     every user's watchlist    │   │
 │  └───────────┬────────────┘          │  4. send + record alerts      │   │
 │              │                        └───────────────┬──────────────┘   │
 │              ▼                                        ▼                   │
 │        ┌──────────────────────────────────────────────────────┐          │
 │        │  Postgres — users, watchlists, trades, rumor signals,│          │
 │        │  alerts sent                                          │          │
 │        └──────────────────────────────────────────────────────┘          │
 └───────────────────────────────────┬──────────────────────────────────────┘
                                     ▼
                         Telegram Bot API (sendMessage)
```

Third parties: **GitHub** (code), **Railway** (hosting + DB + cron),
**Telegram** (login + alerts). Tier 2 adds Reddit/StockTwits APIs.

## Data model (draft)

```
user               id, telegram_user_id, telegram_username, display_name, photo_url,
                   telegram_status (connected | blocked), created_at
company            id, ticker, cik, name, sector, in_sp500
politician         id, bioguide_id, full_name, chamber, party, state, active
watch_company      user_id, company_id, created_at
watch_politician   user_id, politician_id, created_at

trade              id, source (sec_form4 | house_ptr | senate_ptr), source_url, filing_id,
                   company_id?, politician_id?, insider_name, insider_title,
                   ticker, transaction_type (buy | sell | ...), transaction_code,
                   shares?, price?, amount_range?, trade_date, filing_date
rumor_signal       id, platform, post_url, post_date, excerpt,
                   company_id?, politician_id?, confidence = rumor
alert              id, user_id, trade_id? | rumor_signal_id?, sent_at, status
```

`alert` doubles as the dedup record: a user is never sent the same trade twice,
even if the daily job re-runs.

## Telegram integration

1. **Bot setup (owner, once):** create the bot with @BotFather, then run
   `/setdomain` pointing at the app's Railway domain (the login widget only
   works on that registered domain).
2. **Login:** the site embeds Telegram's Login Widget with
   `data-request-access="write"`. Telegram returns the user's id, name, and
   photo plus a signature; the server verifies it (HMAC-SHA256 keyed with
   SHA-256 of the bot token) before creating the session.
3. **Sending:** for private chats, the Telegram user id *is* the chat id, so
   alerts are a direct `sendMessage` call — no `/start` step, no polling or
   webhook needed for v1.
4. **Test notification:** a button on the settings page sends a sample alert
   right away, confirming the connection works.
5. **Blocked bot:** if Telegram returns 403 (user blocked the bot), mark the
   user `blocked` and show a "reconnect" prompt in the UI instead of retrying.

Dev note: the login widget won't run on `localhost`, so local development uses
a dev-only login bypass (disabled in production), and real login is tested on
the Railway deployment.

## Tech stack

- **Language:** Python
- **Web:** FastAPI + Jinja templates + HTMX + Tailwind — one service, one
  language, one deploy, interactive without a separate JS frontend
- **Database:** Postgres (Railway), SQLAlchemy + Alembic migrations
- **Daily job:** same codebase, separate Railway cron service entry point
- **Ingestion:** `httpx`; `lxml`/`BeautifulSoup` for HTML/XML; PDF parsing for
  House PTRs where needed
- **Notifications:** Telegram Bot API over HTTP

## Roadmap

- [x] **Phase 0 — Planning**
- [ ] **Phase 1 — Foundation:** FastAPI skeleton, Postgres schema, Railway
      deploy, Telegram login, "send test notification". Proves the full
      path to your phone before any data work.
- [ ] **Phase 2 — Reference data + watchlists:** load S&P 500 and Congress
      lists; Stocks and Politicians pages with search, filters, star/unstar.
- [ ] **Phase 3 — SEC Form 4 alerts:** daily ingestion, match against starred
      companies, send alerts, alert history page.
- [ ] **Phase 4 — Politician alerts:** House/Senate PTR ingestion, match
      against starred politicians.
- [ ] **Phase 5 — Tier 2 signals:** Reddit/StockTwits ingestion, clearly
      labelled rumor alerts.
- [ ] **Phase 6 — Open up:** onboarding for other users, all US-listed
      stocks, executive-branch officials, per-user alert filters.
- [ ] **Phase 7 — Smarter signals:** cluster buying, unusual size/timing,
      anomaly scoring.

## Decisions

- **Product:** web app with per-user watchlists of stocks (S&P 500 first)
  and politicians (Congress first); alerts only for starred items.
- **Users:** multi-user data model from day one; only the owner uses it
  initially.
- **Freshness:** daily batch.
- **Hosting:** Railway — web service, Postgres, and daily cron job in one
  project, deployed from GitHub.
- **Sign-in + Telegram:** "Log in with Telegram" widget with write access,
  which both authenticates and enables alerts. Replaces the earlier
  "capture chat_id via polling" plan — no inbound bot handling needed in v1.
- **Frontend:** Python-only (FastAPI + HTMX + Tailwind).
- **Signal tiers:** Tier 1 (Form 4, PTRs) confirmed; Tier 2 (web/forum)
  unverified, stored and labelled separately.
- **Which trades alert:** buys and sells only. For Form 4 that means
  open-market purchases and sales (transaction codes `P` and `S`), skipping
  grants, option exercises, and tax withholding. For PTRs, purchases and
  sales (full or partial), skipping exchanges.
- **Alert format:** one Telegram message per trade, no daily digest.
- **Tier 2 sources:** Reddit and StockTwits only for now. More sources get
  added once the app is running well and more signal is wanted.

## Open questions

- None blocking Phase 1. Before Phase 5, confirm current API access terms
  for Reddit and StockTwits, since both have tightened access for new apps
  in the past.
