from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import TELEGRAM_BLOCKED, TELEGRAM_CONNECTED, TELEGRAM_DISCONNECTED, User
from ..telegram import TEST_MESSAGE, TelegramClient, TelegramSendError
from ..web import get_telegram, render, watch_counts

router = APIRouter()

# Pro alert options on the settings page: URL key -> the User field it switches, and how it's explained.
PRO_OPTIONS = {
    "skip-planned-sales": {
        "field": "skip_planned_sales",
        "title": "Skip pre-planned sales",
        "text": "Many executives sell on a schedule they set months ahead (a 10b5-1 trading plan). These sales are "
                "routine and say little about the company. Turn this on to stop getting them.",
        "on": "Pre-planned sales are skipped from now on.",
        "off": "You'll get pre-planned sales again.",
    },
    "notable-feed": {
        "field": "notable_feed",
        "title": "Notable trades from every company",
        "text": "Also get the trades we rate as most notable, even for companies and politicians you haven't "
                "starred. These are mostly directors and officers buying shares in large S&P 500 companies. "
                "About 9 a week on average, fewer in the weeks before earnings.",
        "on": "You'll get notable trades from every company.",
        "off": "Notable trades from other companies are turned off.",
    },
}


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return render(request, "settings.html", {
        "user": user, "counts": watch_counts(db, user), "active": "settings", "test_message": TEST_MESSAGE,
        "pro_options": PRO_OPTIONS,
    })


@router.post("/settings/alerts/{key}", response_class=HTMLResponse)
def toggle_pro_option(request: Request, key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    opt = PRO_OPTIONS.get(key)
    if opt is None:
        return HTMLResponse(status_code=404)
    context = {"key": key, "opt": opt, "user": user}
    if not user.is_pro:
        return render(request, "_pro_option.html", context, toast="This option is part of Pro.")
    on = not getattr(user, opt["field"])
    setattr(user, opt["field"], on)
    db.commit()
    return render(request, "_pro_option.html", context, toast=opt["on"] if on else opt["off"])


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
