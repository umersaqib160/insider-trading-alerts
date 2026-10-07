from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..db import get_db
from ..formatting import market_today
from ..models import STATE_NAMES, Alert, Company, CompanyWatch, Politician, PoliticianWatch, Trade, User
from ..web import render, watch_counts

router = APIRouter()

ACTIVITY_DAYS = 90
PAGE_SIZE = 100
TRADE_LIST_LIMIT = 100
ALERT_HISTORY_LIMIT = 200
TRADE_DETAILS = (selectinload(Trade.insider), selectinload(Trade.congress),
                 selectinload(Trade.company), selectinload(Trade.politician))


def _like(q: str) -> str:
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _checked(value: str) -> bool:
    return value.lower() in {"1", "true", "on", "yes"}


def _latest_trades(db: Session, column, ids: set[int], since: date) -> dict[int, dict]:
    """Latest trade and buy/sell counts per company or politician since a date."""
    if not ids:
        return {}
    trades = db.scalars(
        select(Trade).where(column.in_(ids), Trade.filed_date >= since)
        .order_by(Trade.filed_date.desc(), Trade.id.desc())
    )
    activity: dict[int, dict] = {}
    for trade in trades:
        entry = activity.setdefault(getattr(trade, column.key), {"latest": trade, "buys": 0, "sells": 0})
        entry["buys" if trade.is_buy else "sells"] += 1
    return activity


# ---------- stocks ----------

def _stock_context(db: Session, user: User, q: str, sector: str, sp500: str, starred: str, sort: str, offset: int) -> dict:
    watched = select(CompanyWatch.company_id).where(CompanyWatch.user_id == user.id)
    starred_ids = set(db.scalars(watched))
    stmt = select(Company).where(Company.listed.is_(True))
    q = q.strip()
    if q:
        stmt = stmt.where(or_(
            func.lower(Company.ticker).like(_like(q), escape="\\"),
            func.lower(Company.name).like(_like(q), escape="\\"),
        ))
    if sector:
        stmt = stmt.where(Company.sector == sector)
    if _checked(sp500):
        stmt = stmt.where(Company.in_sp500.is_(True))
    if _checked(starred):
        stmt = stmt.where(Company.id.in_(watched))
    companies = db.scalars(stmt.order_by(Company.ticker)).all()

    today = market_today()
    activity = _latest_trades(db, Trade.company_id, {c.id for c in companies}, today - timedelta(days=ACTIVITY_DAYS))
    sort = sort if sort in {"recent", "activity", "ticker"} else "recent"

    def key(c: Company):
        a = activity.get(c.id)
        if sort == "recent":
            rank = -a["latest"].filed_date.toordinal() if a else 0
        elif sort == "activity":
            rank = -(a["buys"] + a["sells"]) if a else 0
        else:
            rank = 0
        return (c.id not in starred_ids, rank)  # your starred companies first, then the chosen order

    companies = sorted(companies, key=key)
    offset = max(offset, 0)
    return {
        "companies": companies[offset:offset + PAGE_SIZE],
        "matched": len(companies),
        "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < len(companies) else None,
        "activity": activity,
        "today": today,
        "starred_ids": starred_ids,
        "total": db.scalar(select(func.count()).select_from(Company).where(Company.listed.is_(True))) or 0,
        "filters": {"q": q, "sector": sector, "sp500": _checked(sp500), "starred": _checked(starred), "sort": sort},
    }


@router.get("/stocks", response_class=HTMLResponse)
def stocks_page(
    request: Request, q: str = "", sector: str = "", sp500: str = "", starred: str = "", sort: str = "recent",
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    context = _stock_context(db, user, q, sector, sp500, starred, sort, 0)
    context["sectors"] = db.scalars(
        select(Company.sector).where(Company.listed.is_(True), Company.sector != "").distinct().order_by(Company.sector)
    ).all()
    context.update(user=user, counts=watch_counts(db, user), active="stocks")
    return render(request, "stocks.html", context)


@router.get("/stocks/rows", response_class=HTMLResponse)
def stock_rows(
    request: Request, q: str = "", sector: str = "", sp500: str = "", starred: str = "", sort: str = "recent",
    offset: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    context = _stock_context(db, user, q, sector, sp500, starred, sort, offset)
    # Page 1 replaces the whole results block; later pages append rows in place of the "Show more" row.
    return render(request, "_stock_rows.html" if offset == 0 else "_stock_page_rows.html", context)


@router.get("/stocks/{ticker}", response_class=HTMLResponse)
def company_page(request: Request, ticker: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        raise HTTPException(status_code=404)
    trades = db.scalars(
        select(Trade).where(or_(Trade.company_id == company.id, Trade.ticker == company.ticker))
        .options(*TRADE_DETAILS).order_by(Trade.filed_date.desc(), Trade.id.desc()).limit(TRADE_LIST_LIMIT)
    ).all()
    return render(request, "company.html", {
        "company": company, "trades": trades, "today": market_today(),
        "starred": db.get(CompanyWatch, (user.id, company.id)) is not None,
        "user": user, "counts": watch_counts(db, user), "active": "stocks",
    })


@router.post("/watch/company/{ticker}", response_class=HTMLResponse)
def toggle_company(request: Request, ticker: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        raise HTTPException(status_code=404)
    watch = db.get(CompanyWatch, (user.id, company.id))
    if watch:
        db.delete(watch)
    else:
        db.add(CompanyWatch(user_id=user.id, company_id=company.id))
    db.commit()
    on = watch is None
    toast = (f"Starred {company.ticker}. You'll get its next insider or Congress trade."
             if on else f"Removed {company.ticker} from your alerts.")
    return render(request, "_star_response.html", {
        "kind": "company", "key": company.ticker, "label": company.ticker, "on": on,
        "counts": watch_counts(db, user),
    }, toast=toast)


# ---------- politicians ----------

def _politician_context(
    db: Session, user: User, q: str, chamber: str, party: str, state: str, starred: str,
) -> dict:
    watched = select(PoliticianWatch.politician_id).where(PoliticianWatch.user_id == user.id)
    stmt = select(Politician).where(Politician.active.is_(True))
    q = q.strip()
    if q:
        stmt = stmt.where(func.lower(Politician.full_name).like(_like(q), escape="\\"))
    if chamber in {"senate", "house"}:
        stmt = stmt.where(Politician.chamber == chamber)
    if party:
        stmt = stmt.where(Politician.party == party)
    if state:
        stmt = stmt.where(Politician.state == state)
    if _checked(starred):
        stmt = stmt.where(Politician.id.in_(watched))
    starred_ids = set(db.scalars(watched))
    politicians = db.scalars(stmt.order_by(Politician.last_name, Politician.first_name)).all()
    politicians = sorted(politicians, key=lambda p: p.id not in starred_ids)
    today = market_today()
    return {
        "politicians": politicians,
        "activity": _latest_trades(db, Trade.politician_id, {p.id for p in politicians}, today - timedelta(days=365)),
        "today": today,
        "starred_ids": starred_ids,
        "total": db.scalar(select(func.count()).select_from(Politician).where(Politician.active.is_(True))) or 0,
        "filters": {"q": q, "chamber": chamber, "party": party, "state": state, "starred": _checked(starred)},
    }


@router.get("/politicians", response_class=HTMLResponse)
def politicians_page(
    request: Request, q: str = "", chamber: str = "", party: str = "", state: str = "", starred: str = "",
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    context = _politician_context(db, user, q, chamber, party, state, starred)
    states = db.scalars(select(Politician.state).where(Politician.active.is_(True)).distinct()).all()
    context["states"] = sorted(((s, STATE_NAMES.get(s, s)) for s in states), key=lambda s: s[1])
    context.update(user=user, counts=watch_counts(db, user), active="politicians")
    return render(request, "politicians.html", context)


@router.get("/politicians/cards", response_class=HTMLResponse)
def politician_cards(
    request: Request, q: str = "", chamber: str = "", party: str = "", state: str = "", starred: str = "",
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    return render(request, "_politician_cards.html", _politician_context(db, user, q, chamber, party, state, starred))


@router.get("/politicians/{bioguide_id}", response_class=HTMLResponse)
def politician_page(
    request: Request, bioguide_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    politician = db.scalar(select(Politician).where(Politician.bioguide_id == bioguide_id))
    if politician is None:
        raise HTTPException(status_code=404)
    trades = db.scalars(
        select(Trade).where(Trade.politician_id == politician.id)
        .options(*TRADE_DETAILS).order_by(Trade.filed_date.desc(), Trade.id.desc()).limit(TRADE_LIST_LIMIT)
    ).all()
    return render(request, "politician.html", {
        "politician": politician, "trades": trades, "today": market_today(),
        "starred": db.get(PoliticianWatch, (user.id, politician.id)) is not None,
        "user": user, "counts": watch_counts(db, user), "active": "politicians",
    })


@router.post("/watch/politician/{bioguide_id}", response_class=HTMLResponse)
def toggle_politician(
    request: Request, bioguide_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    politician = db.scalar(select(Politician).where(Politician.bioguide_id == bioguide_id))
    if politician is None:
        raise HTTPException(status_code=404)
    watch = db.get(PoliticianWatch, (user.id, politician.id))
    if watch:
        db.delete(watch)
    else:
        db.add(PoliticianWatch(user_id=user.id, politician_id=politician.id))
    db.commit()
    on = watch is None
    name = f"{politician.title} {politician.full_name}"
    toast = f"Starred {name}. You'll get their next reported trade." if on else f"Removed {name} from your alerts."
    return render(request, "_star_response.html", {
        "kind": "politician", "key": politician.bioguide_id, "label": politician.full_name, "on": on,
        "counts": watch_counts(db, user),
    }, toast=toast)


# ---------- alerts ----------

@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    alerts = db.scalars(
        select(Alert).where(Alert.user_id == user.id)
        .options(selectinload(Alert.trade).options(*TRADE_DETAILS))
        .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(ALERT_HISTORY_LIMIT)
    ).all()
    return render(request, "alerts.html", {
        "alerts": alerts, "today": market_today(), "user": user, "counts": watch_counts(db, user), "active": "alerts",
    })
