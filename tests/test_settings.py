from sqlalchemy import select

from app.models import TELEGRAM_BLOCKED, TELEGRAM_CONNECTED, TELEGRAM_DISCONNECTED, User
from app.telegram import TEST_MESSAGE, TelegramSendError

from .conftest import HX, toast_of


def _user(db) -> User:
    user = db.scalar(select(User))
    db.refresh(user)
    return user


def test_settings_page_shows_telegram_account(logged_in):
    html = logged_in.get("/settings").text
    assert "@umer" in html
    assert "Send test notification" in html
    assert "Your Behind The Curtain connection works." in html


def test_send_test_notification(logged_in, telegram):
    response = logged_in.post("/settings/test-notification", headers=HX)
    assert telegram.sent == [(42, TEST_MESSAGE)]
    assert toast_of(response) == "Test notification sent. Check Telegram."


def test_blocked_bot_marks_user_blocked(logged_in, telegram, db):
    telegram.error = TelegramSendError("The bot is blocked.", blocked=True)
    response = logged_in.post("/settings/test-notification", headers=HX)
    assert _user(db).telegram_status == TELEGRAM_BLOCKED
    assert "Bot blocked" in response.text
    assert 'id="me-status" hx-swap-oob="true"' in response.text
    assert toast_of(response) == "The bot is blocked."


def test_other_send_errors_keep_connection(logged_in, telegram, db):
    telegram.error = TelegramSendError("Telegram rejected the message (HTTP 400).")
    response = logged_in.post("/settings/test-notification", headers=HX)
    assert _user(db).telegram_status == TELEGRAM_CONNECTED
    assert toast_of(response) == "Telegram rejected the message (HTTP 400)."


def test_disconnect_pauses_and_blocks_test_sends(logged_in, telegram, db):
    response = logged_in.post("/settings/telegram/disconnect", headers=HX)
    assert _user(db).telegram_status == TELEGRAM_DISCONNECTED
    assert "Connect Telegram" in response.text

    blocked = logged_in.post("/settings/test-notification", headers=HX)
    assert telegram.sent == []
    assert toast_of(blocked) == "Connect Telegram first, then send a test."

    logged_in.post("/settings/telegram/connect", headers=HX)
    assert _user(db).telegram_status == TELEGRAM_CONNECTED


def test_unknown_connection_action_is_404(logged_in):
    assert logged_in.post("/settings/telegram/explode", headers=HX).status_code == 404
