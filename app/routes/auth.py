from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..auth import log_in, optional_user, upsert_telegram_user
from ..config import Settings
from ..db import get_db
from ..models import User
from ..telegram import TelegramAuthError, TelegramLogin, verify_login
from ..web import get_app_settings, render

router = APIRouter()

LOGIN_ERRORS = {
    "invalid": "That Telegram login couldn't be verified. Try logging in again.",
    "expired": "That Telegram login link has expired. Log in again.",
    "unconfigured": "Telegram login isn't set up on this server yet.",
}


@router.get("/")
def home(user: User | None = Depends(optional_user)) -> Response:
    return RedirectResponse("/stocks" if user else "/login", status_code=303)


@router.get("/login")
def login_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(optional_user),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    if user:
        return RedirectResponse("/stocks", status_code=303)
    telegram_ready = bool(settings.telegram_bot_token and settings.telegram_bot_username)
    return render(request, "login.html", {
        "error": LOGIN_ERRORS.get(error or ""),
        "bot_username": settings.telegram_bot_username if telegram_ready else None,
        "auth_url": str(request.url_for("telegram_callback")),
        "dev_login": settings.dev_login_enabled,
    })


@router.get("/auth/telegram", name="telegram_callback")
def telegram_callback(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    try:
        login = verify_login(request.query_params, settings.telegram_bot_token)
    except TelegramAuthError as exc:
        return RedirectResponse(f"/login?error={exc.code}", status_code=303)
    log_in(request, upsert_telegram_user(db, login))
    return RedirectResponse("/stocks", status_code=303)


@router.post("/auth/dev-login")
def dev_login(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    if not settings.dev_login_enabled:
        raise HTTPException(status_code=404)
    login = TelegramLogin(
        id=settings.dev_telegram_id, first_name="Dev", last_name="User",
        username="dev_user", photo_url=None, auth_date=0,
    )
    log_in(request, upsert_telegram_user(db, login))
    return RedirectResponse("/stocks", status_code=303)


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
