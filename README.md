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

## Proposed architecture

```
                 ┌────────────────────┐
                 │  Daily batch job     │  (cron / APScheduler, once/day)
                 └─────────┬──────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │ SEC Form 4   │  │ House PTR    │  │ Senate PTR   │   Ingestion
 │ poller       │  │ scraper      │  │ scraper      │   (per-source)
 └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
        └─────────────────┼─────────────────┘
                           ▼
                 ┌───────────────────┐
                 │  Normalizer         │  → common `Trade` schema
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Postgres storage   │  trades, entities, rules, users/subscriptions
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Signal engine      │  rule-based first; anomaly scoring later
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Telegram bot        │  primary notification channel
                 │  (email/webhook later)│
                 └───────────────────┘
                           │
                 ┌───────────────────┐
                 │  API + dashboard    │  browse trades, manage alert rules
                 └───────────────────┘
```

The pipeline runs once a day: pull the day's new filings from all three
sources, normalize, evaluate signal rules, and push any resulting alerts out
over Telegram. No streaming/real-time polling for v1 — SEC Form 4 has up to a
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
- **Ingestion/scheduling:** `requests`/`httpx` + a once-daily `APScheduler`/cron
  job (no need for distributed workers at this scale)
- **Parsing:** `lxml`/`BeautifulSoup` for HTML/PDF disclosure parsing
- **Storage:** PostgreSQL
- **API:** FastAPI
- **Notifications:** Telegram bot (`python-telegram-bot`), sending one
  message per alert to each subscribed user's chat. Notification layer stays
  pluggable so email/Slack/Discord can be added later, but Telegram is the
  only channel built for v1.

## Roadmap

- [ ] **Phase 0 — Planning** *(current)*: finalize data model, pick which
      source to build first
- [ ] **Phase 1 — SEC Form 4 ingestion**: poll EDGAR, parse filings, store
      normalized trades
- [ ] **Phase 2 — Politician disclosures**: House/Senate PTR ingestion
      (likely the harder parsing problem)
- [ ] **Phase 3 — Signal engine v1**: rule-based alerts on the unified trade
      table
- [ ] **Phase 4 — Telegram notifications**: bot setup, chat linking,
      per-user alert delivery on the daily batch
- [ ] **Phase 5 — API + dashboard**: browse trades, manage alerts
- [ ] **Phase 6 — Anomaly scoring**: move beyond static rules if warranted

## Decisions

- **Freshness:** daily batch, not real-time polling (see architecture
  section for rationale).
- **Users:** multi-user data model from day one (users, Telegram chat links,
  per-user alert rules), but only the project owner as an actual user for
  now.
- **Notifications:** Telegram bot is the v1 delivery channel.

## Open questions

- Hosting target (self-hosted, cloud VM, serverless) — affects scheduler
  choice and how the daily job + Telegram bot get deployed.
- Telegram bot mode: polling (`getUpdates`) vs. webhook — polling is simpler
  to run for a single daily job with no server; webhook needs a public HTTPS
  endpoint but is cleaner if we later want `/commands` handled in real time.
