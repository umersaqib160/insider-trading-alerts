from datetime import date, timedelta
from itertools import count

from sqlalchemy import select

from app.formatting import market_today
from app.models import (
    BUY, SELL, SOURCE_FORM4, Company, CongressTradeDetail, InsiderTradeDetail, Politician, Trade,
)

_ids = count(1)


def insider_trade(
    db, ticker: str, *, buy: bool = True, value: float | None = 1_006_000, days_ago: int = 1,
    name: str = "Timothy D Cook", role: str = "Chief Executive Officer", shares: float = 4000,
    avg_price: float | None = 251.5, plan: bool = False, owned_after: float | None = None,
    filed: date | None = None, traded: date | None = None, commit: bool = True,
) -> Trade:
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    filed = filed or market_today() - timedelta(days=days_ago)
    n = next(_ids)
    trade = Trade(
        source=SOURCE_FORM4, external_id=f"acc-{n}:{'P' if buy else 'S'}", company_id=company.id if company else None,
        ticker=ticker, asset_name=company.name if company else ticker, actor_name=name, actor_role=role,
        direction=BUY if buy else SELL, value_low=value, value_high=value,
        trade_date=traded or filed - timedelta(days=2), filed_date=filed,
        source_url="https://www.sec.gov/Archives/edgar/data/320193/x-index.htm", tags=[],
    )
    trade.insider = InsiderTradeDetail(accession_no=f"acc-{n}", transaction_code="P" if buy else "S", shares=shares,
                                       avg_price=avg_price, shares_owned_after=owned_after, is_10b5_1=plan)
    db.add(trade)
    if commit:
        db.commit()
    return trade


def congress_trade(
    db, bioguide_id: str, ticker: str, *, buy: bool = True, low: float = 15_001, high: float | None = 50_000,
    days_ago: int = 1, traded_days_before: int = 30, owner: str = "Spouse", commit: bool = True,
) -> Trade:
    politician = db.scalar(select(Politician).where(Politician.bioguide_id == bioguide_id))
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    filed = market_today() - timedelta(days=days_ago)
    label = f"${low:,.0f} - ${high:,.0f}" if high else f"Over ${low:,.0f}"
    trade = Trade(
        source=politician.chamber, external_id=f"q-{next(_ids)}", company_id=company.id if company else None,
        politician_id=politician.id, ticker=ticker, asset_name=company.name if company else ticker,
        actor_name=politician.full_name, actor_role=f"{politician.role_label} ({politician.short_label})",
        direction=BUY if buy else SELL, value_low=low, value_high=high,
        trade_date=filed - timedelta(days=traded_days_before), filed_date=filed,
        source_url="https://efdsearch.senate.gov/search/", tags=[],
    )
    trade.congress = CongressTradeDetail(chamber=politician.chamber, owner=owner, amount_range=label,
                                         transaction_type="Purchase" if buy else "Sale (Full)", description="")
    db.add(trade)
    if commit:
        db.commit()
    return trade
