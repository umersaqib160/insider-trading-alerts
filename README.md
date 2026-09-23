# Insider Trading Alerts

A signal alert system that monitors **public disclosures** of stock trades by
corporate executives/directors and US politicians, and surfaces notable
activity (large trades, cluster buying, unusual timing) as alerts.

> **Scope note:** This project only ever touches information that is legally
> required to be disclosed publicly — SEC Form 4 filings and STOCK Act
> Periodic Transaction Reports. It does not use, infer, or trade on any
> nonpublic information. It is a monitoring/aggregation tool, in the same
> category as sites like Capitol Trades, Quiver Quantitative, or Unusual
> Whales.

## Status

📋 **Planning stage.** No code yet — this README is the working plan. Nothing
here is final; it's a starting point to build from once the design settles.

## Signal sources

| Source | Who | Filing | Disclosure window | Access |
|---|---|---|---|---|
| SEC Form 4 | Company executives, directors, 10%+ owners | Statement of Changes in Beneficial Ownership | Within 2 business days of trade | [SEC EDGAR full-text search](https://efts.sec.gov/LATEST/search-index) / Atom feeds, free, no key required |
| House PTR | US House Representatives | Periodic Transaction Report | Within 45 days of trade | House Clerk's [Financial Disclosure site](https://disclosures-clerk.house.gov/) (PDF-based, needs parsing) |
| Senate PTR | US Senators | Periodic Transaction Report | Within 45 days of trade | Senate [eFD system](https://efdsearch.senate.gov/) (requires session-based search, needs parsing) |

Community-maintained parsers already exist for the House/Senate PTR data
(e.g. Senate Stock Watcher / House Stock Watcher projects) — worth evaluating
as a starting point rather than parsing PDFs from scratch.

### Tier 2: unverified web/forum signals

Regulatory filings are confirmed but lagging (up to 45 days for politicians).
Chatter on forums, social media, and financial discussion sites sometimes
surfaces the same trades earlier — but it's rumor, not disclosure. This tier
is kept explicitly separate so alerts never blur "SEC confirmed this" with
"someone on a forum claimed this."

Candidate sources for v1 (start narrow, expand later):
- Reddit (via the official Reddit API, not raw scraping — subreddits like
  r/wallstreetbets, r/investing, r/SecurityAnalysis)
- StockTwits (has a public API for ticker-tagged posts)
- X/Twitter search on cashtags + insider-trading-related keywords (official
  API is paid; evaluate cost vs. value before committing)
- Financial news aggregators/RSS for "insider buying/selling" coverage

Practical constraints to design around:
- **Confidence, not fact:** every item from this tier gets a `confidence:
  rumor` tag and is never merged into the Tier 1 `Trade` table — it's a
  separate `RumorSignal` record, cross-referenced by ticker/person where
  possible.
- **Signal-to-noise:** raw keyword scraping of the open web is mostly noise.
  Practical v1 approach is to match forum/social chatter against
  people/tickers already being watched (from Tier 1 data), not to crawl
  blindly.
- **Access method matters:** prefer official APIs (Reddit, StockTwits) over
  scraping HTML — more stable, less likely to get rate-limited or blocked,
  and avoids ToS issues.

## Proposed architecture

```
                 ┌────────────────────┐
                 │  GitHub Actions      │  scheduled workflow, once/day
                 │  (cron)              │
                 └─────────┬──────────┘
                           │
    ┌────────────────┬─────┴────┬────────────────┐
    ▼                ▼          ▼                ▼
┌─────────┐  ┌───────────┐ ┌───────────┐ ┌────────────────┐
│ SEC Form 4│  │ House PTR  │ │ Senate PTR │ │ Web/forum       │  Ingestion
│ poller    │  │ scraper    │ │ scraper    │ │ scanner (Tier 2)│  (per-source)
└─────┬────┘  └─────┬─────┘ └─────┬─────┘ └────────┬───────┘
      └──────────────┼─────────────┼───────────────┘
                       ▼
                 ┌───────────────────┐
                 │  Normalizer         │  → `Trade` (Tier 1) / `RumorSignal` (Tier 2)
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  SQLite (in-repo)   │  trades, rumor signals, rules, users
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Signal engine      │  rule-based first; anomaly scoring later
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Telegram sendMessage│  one HTTP call per alert, per user
                 └───────────────────┘
                           │
                 ┌───────────────────┐
                 │  API + dashboard    │  browse trades, manage alert rules
                 │  (later phase)       │
                 └───────────────────┘
```

The pipeline runs once a day as a GitHub Actions workflow: pull the day's new
filings/signals from all sources, normalize, evaluate signal rules, push any
resulting alerts to Telegram, and commit the updated SQLite state file back
to the repo. No streaming/real-time polling for v1 — SEC Form 4 has up to a
2-day disclosure lag and PTRs up to 45 days anyway, so daily batch loses
essentially no signal freshness while being far simpler to build and run.

### Common `Trade` schema (draft)

```
person_name, person_role (exec | politician), person_title, chamber (house|senate, if applicable)
entity_name, ticker
transaction_type (buy | sell | option_exercise | gift | ...)
amount_range (disclosures are often reported as ranges, not exact figures)
trade_date, filing_date, filing_lag_days
source (sec_form4 | house_ptr | senate_ptr), source_url
```

### `RumorSignal` schema (draft, Tier 2)

```
person_name (if identifiable), ticker (if identifiable)
platform (reddit | stocktwits | twitter | news), post_url, post_date
excerpt, matched_watch (which Tier 1 person/ticker this matched against)
confidence: rumor   # always — never promoted into the Trade table automatically
```

### Users & subscriptions (draft)

Data model is multi-user from day one — even though only one person (the
project owner) will actually use it for now:

```
user: id, email, created_at
telegram_chat: user_id, chat_id (from Telegram's getUpdates/webhook), linked_at
alert_rule: user_id, rule_type, params (e.g. min_trade_value, tickers watched, roles watched)
```

Onboarding a Telegram recipient: user starts a chat with the bot, sends
`/start`, bot captures the resulting `chat_id` and links it to their account
(a `/start <token>` deep link is the standard pattern once there's a real
signup flow — for now, with a single user, the owner's `chat_id` can just be
linked manually).

### Initial signal rules (v1, rule-based)

- Trade size in the top percentile for that person/entity
- Multiple insiders/politicians trading the same ticker within a short window
- Unusually short filing lag (fast disclosure can itself be notable)
- Trade shortly before major news/earnings (requires a news/earnings calendar
  feed — later phase)

## Tech stack (initial choice)

- **Language:** Python
- **Hosting/scheduling:** GitHub Actions scheduled workflow (`schedule:` cron
  trigger), once/day. Free (unlimited minutes on a public repo), no new
  vendor, and the same platform already hosting the code.
- **Ingestion:** `requests`/`httpx` for Tier 1 (SEC/House/Senate) and Tier 2
  (Reddit/StockTwits APIs, RSS)
- **Parsing:** `lxml`/`BeautifulSoup` for HTML/PDF disclosure parsing
- **Storage:** SQLite file committed back to the repo by the workflow after
  each run — keeps state versioned and avoids standing up a hosted database
  for v1. Swappable for Postgres later if scale/concurrency needs it.
- **API:** FastAPI (later phase, once there's a dashboard to serve)
- **Notifications:** Telegram Bot API, called directly over HTTP
  (`sendMessage` per alert per user) — no persistent bot process needed for
  v1 since delivery is one-directional. Notification layer stays pluggable
  so email/Slack/Discord can be added later.

## Roadmap

- [ ] **Phase 0 — Planning** *(current)*: finalize data model, pick which
      source to build first
- [ ] **Phase 1 — SEC Form 4 ingestion**: poll EDGAR, parse filings, store
      normalized trades
- [ ] **Phase 2 — Politician disclosures**: House/Senate PTR ingestion
      (likely the harder parsing problem)
- [ ] **Phase 3 — Signal engine v1**: rule-based alerts on the unified trade
      table
- [ ] **Phase 4 — Telegram notifications**: bot setup, one-time chat_id
      capture, per-user alert delivery on the daily batch
- [ ] **Phase 5 — Web/forum signals (Tier 2)**: Reddit/StockTwits ingestion,
      matched against Tier 1 watched people/tickers, delivered as clearly-
      marked rumor-tier alerts
- [ ] **Phase 6 — API + dashboard**: browse trades, manage alerts
- [ ] **Phase 7 — Anomaly scoring**: move beyond static rules if warranted

## Decisions

- **Freshness:** daily batch, not real-time polling (see architecture
  section for rationale).
- **Users:** multi-user data model from day one (users, Telegram chat links,
  per-user alert rules), but only the project owner as an actual user for
  now.
- **Notifications:** Telegram, delivered via direct API calls from the daily
  job (no persistent bot process needed for v1's one-directional alerts).
- **Hosting:** GitHub Actions scheduled workflow + SQLite state committed to
  the repo. Keeps the stack to two third parties total — GitHub (already in
  use) and Telegram — with no server to provision or pay for. Revisit if/when
  interactive bot commands or multi-user self-onboarding need an always-on
  process (small VPS/Fly.io/Railway at that point).
- **Signal sources:** three tiers — SEC Form 4, House/Senate PTR (Tier 1,
  confirmed), and web/forum chatter (Tier 2, unverified) — kept in separate
  tables so rumor never gets presented as confirmed disclosure.

## Open questions

- Tier 2 source prioritization: start with Reddit + StockTwits (free APIs)
  and add X/Twitter later once the paid API cost is worth it?
- At what point (user count, message volume) does GitHub Actions' daily cron
  stop being sufficient, and what's the trigger to move to an always-on host?
