import json
import time

import httpx
import pytest

from app.telegram import TelegramAuthError, TelegramClient, TelegramSendError, verify_login

from .conftest import BOT_TOKEN, login_params, sign


def test_verify_login_accepts_valid_signature():
    login = verify_login(login_params(telegram_id=7, last_name="Saqib"), BOT_TOKEN)
    assert (login.id, login.first_name, login.last_name, login.username) == (7, "Umer", "Saqib", "umer")


def test_verify_login_rejects_tampered_field():
    params = login_params()
    params["id"] = "999"
    with pytest.raises(TelegramAuthError) as exc:
        verify_login(params, BOT_TOKEN)
    assert exc.value.code == "invalid"


def test_verify_login_rejects_missing_hash():
    params = login_params()
    del params["hash"]
    with pytest.raises(TelegramAuthError, match="invalid"):
        verify_login(params, BOT_TOKEN)


def test_verify_login_rejects_other_bots_signature():
    with pytest.raises(TelegramAuthError, match="invalid"):
        verify_login(login_params(), "999:OTHER-BOT")


def test_verify_login_rejects_expired_login():
    params = sign({"id": "1", "first_name": "A", "auth_date": str(int(time.time()) - 2 * 24 * 60 * 60)})
    with pytest.raises(TelegramAuthError) as exc:
        verify_login(params, BOT_TOKEN)
    assert exc.value.code == "expired"


def test_verify_login_needs_bot_token():
    with pytest.raises(TelegramAuthError, match="unconfigured"):
        verify_login(login_params(), "")


def _client(handler) -> TelegramClient:
    return TelegramClient(BOT_TOKEN, httpx.Client(transport=httpx.MockTransport(handler)))


def test_send_message_posts_html_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    _client(handler).send_message(42, "<b>Hi</b>")
    assert seen["url"] == f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    assert seen["body"] == {"chat_id": 42, "text": "<b>Hi</b>", "parse_mode": "HTML", "disable_web_page_preview": True}


def test_send_message_reports_blocked_bot():
    client = _client(lambda r: httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}))
    with pytest.raises(TelegramSendError) as exc:
        client.send_message(42, "hi")
    assert exc.value.blocked


def test_send_message_reports_other_failures():
    client = _client(lambda r: httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}))
    with pytest.raises(TelegramSendError) as exc:
        client.send_message(42, "hi")
    assert not exc.value.blocked
    assert "400" in exc.value.message


def test_send_message_network_error_does_not_leak_token():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TelegramSendError) as exc:
        _client(handler).send_message(42, "hi")
    assert BOT_TOKEN not in str(exc.value)
    assert exc.value.__cause__ is None


def test_send_message_without_token():
    with pytest.raises(TelegramSendError, match="isn't configured"):
        TelegramClient("").send_message(42, "hi")
