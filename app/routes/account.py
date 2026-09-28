from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import TELEGRAM_BLOCKED, TELEGRAM_CONNECTED, TELEGRAM_DISCONNECTED, User
from ..telegram import TEST_MESSAGE, TelegramClient, TelegramSendError
from ..web import get_telegram, render, watch_counts

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return render(request, "settings.html", {
        "user": user, "counts": watch_counts(db, user), "active": "settings", "test_message": TEST_MESSAGE,
    })


@router.post("/settings/test-notification", response_class=HTMLResponse)
def send_test_notification(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    telegram: TelegramClient = Depends(get_telegram),
):
    if user.telegram_status != TELEGRAM_CONNECTED:
        return render(request, "_telegram_state.html", {"user": user, "oob": True},
                      toast="Connect Telegram first, then send a test.")
    try:
        telegram.send_message(user.telegram_id, TEST_MESSAGE)
    except TelegramSendError as exc:
        if exc.blocked:
            user.telegram_status = TELEGRAM_BLOCKED
            db.commit()
        return render(request, "_telegram_state.html", {"user": user, "oob": True}, toast=exc.message)
    return render(request, "_telegram_state.html", {"user": user, "oob": True}, toast="Test notification sent. Check Telegram.")


@router.post("/settings/telegram/{action}", response_class=HTMLResponse)
def set_telegram_connection(
    request: Request, action: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    if action == "disconnect":
        user.telegram_status = TELEGRAM_DISCONNECTED
        toast = "Telegram disconnected. Alerts are paused."
    elif action == "connect":
        user.telegram_status = TELEGRAM_CONNECTED
        toast = "Telegram connected. Send a test to confirm it works."
    else:
        return HTMLResponse(status_code=404)
    db.commit()
    return render(request, "_telegram_state.html", {"user": user, "oob": True}, toast=toast)


@router.post("/settings/unverified", response_class=HTMLResponse)
def set_unverified(
    request: Request, enabled: str = Form(""),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    user.include_unverified = enabled == "on"
    db.commit()
    toast = "Unverified forum signals turned on." if user.include_unverified else "Unverified forum signals turned off."
    return render(request, "_empty.html", toast=toast)
