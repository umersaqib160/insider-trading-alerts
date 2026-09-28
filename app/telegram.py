import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

LOGIN_MAX_AGE_SECONDS = 24 * 60 * 60
API_BASE = "https://api.telegram.org"

TEST_MESSAGE = (
    "<b>Test alert</b>\n"
    "Your Behind The Curtain connection works. "
    "Alerts for your starred companies and politicians will arrive here."
)


class TelegramAuthError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TelegramLogin:
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    photo_url: str | None
    auth_date: int


def verify_login(
    params: Mapping[str, str],
    bot_token: str,
    now: float | None = None,
    max_age: int = LOGIN_MAX_AGE_SECONDS,
) -> TelegramLogin:
    """Check a Telegram Login Widget callback (https://core.telegram.org/widgets/login#checking-authorization)."""
    if not bot_token:
        raise TelegramAuthError("unconfigured")
    data = dict(params)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise TelegramAuthError("invalid")

    check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise TelegramAuthError("invalid")

    try:
        user_id = int(data["id"])
        auth_date = int(data["auth_date"])
    except (KeyError, ValueError):
        raise TelegramAuthError("invalid") from None
    if (time.time() if now is None else now) - auth_date > max_age:
        raise TelegramAuthError("expired")

    return TelegramLogin(
        id=user_id,
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name") or None,
        username=data.get("username") or None,
        photo_url=data.get("photo_url") or None,
        auth_date=auth_date,
    )


class TelegramSendError(Exception):
    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.message = message
        self.blocked = blocked


class TelegramClient:
    def __init__(self, bot_token: str, http: httpx.Client | None = None):
        self._token = bot_token
        self._http = http or httpx.Client(timeout=10)

    def send_message(self, chat_id: int, text: str) -> None:
        if not self._token:
            raise TelegramSendError("The Telegram bot isn't configured yet.")
        try:
            response = self._http.post(
                f"{API_BASE}/bot{self._token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
        except httpx.HTTPError:
            # The exception text includes the request URL, which contains the bot token.
            raise TelegramSendError("Couldn't reach Telegram. Try again in a minute.") from None

        if response.status_code == 403:
            raise TelegramSendError(
                "Telegram refused the message because the bot is blocked. Unblock it in Telegram, then reconnect.",
                blocked=True,
            )
        try:
            ok = response.status_code == 200 and response.json().get("ok") is True
        except ValueError:
            ok = False
        if not ok:
            raise TelegramSendError(f"Telegram rejected the message (HTTP {response.status_code}).")
