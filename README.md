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
                 ┌────────────────┐
                 │   Schedulers    │  (cron / APScheduler)
                 └───────┬────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
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
                 │  Postgres storage   │  trades, entities, rules, subscribers
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Signal engine      │  rule-based first; anomaly scoring later
                 └─────────┬──────────┘
                           ▼
                 ┌───────────────────┐
                 │  Notification layer │  email / Slack / Discord / webhook
                 └───────────────────┘
                           │
                 ┌───────────────────┐
                 │  API + dashboard    │  browse trades, manage alert rules
                 └───────────────────┘
```

### Common `Trade` schema (draft)

```
person_name, person_role (exec | politician), person_title, chamber (house|senate, if applicable)
entity_name, ticker
transaction_type (buy | sell | option_exercise | gift | ...)
amount_range (disclosures are often reported as ranges, not exact figures)
trade_date, filing_date, filing_lag_days
source (sec_form4 | house_ptr | senate_ptr), source_url
```

### Initial signal rules (v1, rule-based)

- Trade size in the top percentile for that person/entity
- Multiple insiders/politicians trading the same ticker within a short window
- Unusually short filing lag (fast disclosure can itself be notable)
- Trade shortly before major news/earnings (requires a news/earnings calendar
  feed — later phase)

## Tech stack (initial choice)

- **Language:** Python
- **Ingestion/scheduling:** `requests`/`httpx` + `APScheduler` (or Celery beat
  if we need distributed workers later)
- **Parsing:** `lxml`/`BeautifulSoup` for HTML/PDF disclosure parsing
- **Storage:** PostgreSQL
- **API:** FastAPI
- **Notifications:** pluggable — start with email (SMTP) and a generic
  webhook, add Slack/Discord/Telegram as needed

## Roadmap

- [ ] **Phase 0 — Planning** *(current)*: finalize data model, pick which
      source to build first
- [ ] **Phase 1 — SEC Form 4 ingestion**: poll EDGAR, parse filings, store
      normalized trades
- [ ] **Phase 2 — Politician disclosures**: House/Senate PTR ingestion
      (likely the harder parsing problem)
- [ ] **Phase 3 — Signal engine v1**: rule-based alerts on the unified trade
      table
- [ ] **Phase 4 — Notifications**: email/webhook delivery, per-user
      subscription rules
- [ ] **Phase 5 — API + dashboard**: browse trades, manage alerts
- [ ] **Phase 6 — Anomaly scoring**: move beyond static rules if warranted

## Open questions

- Real-time-ish polling vs. daily batch — how fresh do alerts need to be?
- Multi-user product (accounts, subscriptions) vs. single-user tool for now?
- Hosting target (self-hosted, cloud VM, serverless) — affects scheduler
  choice.
