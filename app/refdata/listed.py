from dataclasses import dataclass, field

# SEC's list of every ticker it knows, with the exchange it trades on.
LISTED_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
# OTC is left out on purpose: mostly thinly traded penny stocks.
LISTED_EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}


@dataclass
class ListedCompany:
    cik: str
    name: str
    ticker: str
    exchange: str
    other_tickers: list[str] = field(default_factory=list)


def normalize_ticker(ticker: str) -> str:
    """SEC writes share classes as BRK-B; the S&P list and most data feeds use BRK.B."""
    return ticker.strip().upper().replace("-", ".")


def parse_listed(payload: dict) -> list[ListedCompany]:
    """One entry per company. SEC lists each company's main ticker first, then other classes or preferreds."""
    columns = payload["fields"]
    by_cik: dict[str, ListedCompany] = {}
    for row in payload["data"]:
        item = dict(zip(columns, row))
        if item.get("exchange") not in LISTED_EXCHANGES or not item.get("ticker") or not item.get("cik"):
            continue
        cik = str(item["cik"]).zfill(10)
        ticker = normalize_ticker(item["ticker"])
        company = by_cik.get(cik)
        if company is None:
            by_cik[cik] = ListedCompany(cik=cik, name=(item.get("name") or "").strip(), ticker=ticker,
                                        exchange=item["exchange"])
        elif ticker != company.ticker and ticker not in company.other_tickers:
            company.other_tickers.append(ticker)
    return list(by_cik.values())


def parse_sic(payload: dict) -> tuple[int | None, str]:
    raw = str(payload.get("sic") or "").strip()
    return (int(raw) if raw.isdigit() else None), (payload.get("sicDescription") or "").strip()
