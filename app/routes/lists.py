from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..db import get_db
from ..jobs import market_today
from ..models import STATE_NAMES, Alert, Company, CompanyWatch, Politician, PoliticianWatch, Trade, User
from ..web import render, watch_counts

router = APIRouter()

ACTIVITY_DAYS = 90
COMPANY_TRADE_LIMIT = 100
ALERT_HISTORY_LIMIT = 200


def _like(q: str) -> str:
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _checked(value: str) -> bool:
    return value.lower() in {"1", "true", "on", "yes"}


# ---------- stocks ----------

def _activity(db: Session, company_ids: list[int], today: date) -> dict[int, dict]:
    since = today - timedelta(days=ACTIVITY_DAYS)
    trades = db.scalars(
        select(Trade).where(Trade.company_id.in_(company_ids), Trade.filed_date >= since)
        .order_by(Trade.filed_date.desc(), Trade.id.desc())
    )
    activity: dict[int, dict] = {}
    for trade in trades:
        entry = activity.setdefault(trade.company_id, {"latest": trade, "buys": 0, "sells": 0})
        entry["buys" if trade.is_buy else "sells"] += 1
    return activity


def _stock_context(db: Session, user: User, q: str, sector: str, starred: str, sort: str) -> dict:
    watched = select(CompanyWatch.company_id).where(CompanyWatch.user_id == user.id)
    stmt = select(Company).where(Company.in_sp500.is_(True))
    q = q.strip()
    if q:
        stmt = stmt.where(or_(
            func.lower(Company.ticker).like(_like(q), escape="\\"),
            func.lower(Company.name).like(_like(q), escape="\\"),
        ))
    if sector:
        stmt = stmt.where(Company.sector == sector)
    if _checked(starred):
        stmt = stmt.where(Company.id.in_(watched))
    companies = db.scalars(stmt.order_by(Company.ticker)).all()
    today = market_today()
    activity = _activity(db, [c.id for c in companies], today)
    sort = sort if sort in {"recent", "activity", "ticker"} else "recent"
    if sort == "recent":
        # Newest insider trade first; companies without one keep ticker order at the end.
        companies = sorted(companies, key=lambda c: -activity[c.id]["latest"].filed_date.toordinal() if c.id in activity else 0)
    elif sort == "activity":
        companies = sorted(companies, key=lambda c: -(activity[c.id]["buys"] + activity[c.id]["sells"]) if c.id in activity else 0)
    return {
        "companies": companies,
        "activity": activity,
        "today": today,
        "starred_ids": set(db.scalars(watched)),
        "total": db.scalar(select(func.count()).select_from(Company).where(Company.in_sp500.is_(True))) or 0,
        "filters": {"q": q, "sector": sector, "starred": _checked(starred), "sort": sort},
    }


@router.get("/stocks", response_class=HTMLResponse)
def stocks_page(
    request: Request, q: str = "", sector: str = "", starred: str = "", sort: str = "recent",
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    context = _stock_context(db, user, q, sector, starred, sort)
    context["sectors"] = db.scalars(
        select(Company.sector).where(Company.in_sp500.is_(True), Company.sector != "").distinct().order_by(Company.sector)
    ).all()
    context.update(user=user, counts=watch_counts(db, user), active="stocks")
    return render(request, "stocks.html", context)


@router.get("/stocks/rows", response_class=HTMLResponse)
def stock_rows(
    request: Request, q: str = "", sector: str = "", starred: str = "", sort: str = "recent",
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    return render(request, "_stock_rows.html", _stock_context(db, user, q, sector, starred, sort))


@router.get("/stocks/{ticker}", response_class=HTMLResponse)
def company_page(
    request: Request, ticker: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        raise HTTPException(status_code=404)
    trades = db.scalars(
        select(Trade).where(Trade.company_id == company.id)
        .order_by(Trade.filed_date.desc(), Trade.id.desc()).limit(COMPANY_TRADE_LIMIT)
    ).all()
    return render(request, "company.html", {
        "company": company, "trades": trades, "today": market_today(),
        "starred": db.get(CompanyWatch, (user.id, company.id)) is not None,
        "user": user, "counts": watch_counts(db, user), "active": "stocks",
    })


@router.post("/watch/company/{ticker}", response_class=HTMLResponse)
def toggle_company(
    request: Request, ticker: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
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
    toast = (f"Starred {company.ticker}. Alerts start from the next daily check."
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
    return {
        "politicians": politicians,
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


@router.post("/watch/politician/{bioguide_id}", response_class=HTMLResponse)
def toggle_politician(
    request: Request, bioguide_id: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
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
    toast = f"Starred {name}. Alerts start from the next daily check." if on else f"Removed {name} from your alerts."
    return render(request, "_star_response.html", {
        "kind": "politician", "key": politician.bioguide_id, "label": politician.full_name, "on": on,
        "counts": watch_counts(db, user),
    }, toast=toast)


# ---------- alerts ----------

@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    alerts = db.scalars(
        select(Alert).where(Alert.user_id == user.id)
        .options(selectinload(Alert.trade).selectinload(Trade.company))
        .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(ALERT_HISTORY_LIMIT)
    ).all()
    return render(request, "alerts.html", {
        "alerts": alerts, "user": user, "counts": watch_counts(db, user), "active": "alerts",
    })
