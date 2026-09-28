import json
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .formatting import days_ago, money, shares, short_date
from .models import CompanyWatch, PoliticianWatch, User
from .telegram import TelegramClient

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters.update(money=money, shares=shares, short_date=short_date, days_ago=days_ago)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_telegram(request: Request) -> TelegramClient:
    return TelegramClient(request.app.state.settings.telegram_bot_token)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def watch_counts(db: Session, user: User) -> dict[str, int]:
    return {
        "stocks": db.scalar(select(func.count()).select_from(CompanyWatch).where(CompanyWatch.user_id == user.id)) or 0,
        "politicians": db.scalar(select(func.count()).select_from(PoliticianWatch).where(PoliticianWatch.user_id == user.id)) or 0,
    }


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    toast: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    headers = {"HX-Trigger": json.dumps({"showToast": {"message": toast}})} if toast else None
    return templates.TemplateResponse(request, name, context or {}, status_code=status_code, headers=headers)
