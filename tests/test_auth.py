import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.models import TELEGRAM_BLOCKED, TELEGRAM_CONNECTED, User

from .conftest import HX, login_params


@pytest.mark.parametrize("path", ["/stocks", "/politicians", "/alerts", "/settings"])
def test_pages_redirect_to_login_when_signed_out(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_htmx_requests_get_client_side_redirect_when_signed_out(client):
    response = client.post("/watch/company/AAPL", headers=HX)
    assert response.headers["HX-Redirect"] == "/login"


def test_home_redirects_by_login_state(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    client.get("/auth/telegram", params=login_params())
    assert client.get("/", follow_redirects=False).headers["location"] == "/stocks"


def test_login_page_embeds_telegram_widget(client):
    html = client.get("/login").text
    assert 'data-telegram-login="btc_test_bot"' in html
    assert 'data-request-access="write"' in html
    assert 'data-auth-url="http://testserver/auth/telegram"' in html
    assert "Dev login" not in html


def test_login_page_explains_missing_bot_config(make_client):
    html = make_client(telegram_bot_token="", telegram_bot_username="").get("/login").text
    assert "telegram-widget.js" not in html
    assert "isn't set up yet" in html


def test_telegram_login_creates_user_and_session(client, db):
    response = client.get("/auth/telegram", params=login_params(telegram_id=42, last_name="Saqib"), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/stocks"
    user = db.scalar(select(User))
    assert (user.telegram_id, user.first_name, user.last_name, user.username) == (42, "Umer", "Saqib", "umer")
    page = client.get("/stocks")
    assert page.status_code == 200
    assert "Umer Saqib" in page.text


def test_repeat_login_updates_user_and_reconnects_blocked_bot(client, db):
    client.get("/auth/telegram", params=login_params(telegram_id=42))
    user = db.scalar(select(User))
    user.telegram_status = TELEGRAM_BLOCKED
    db.commit()

    client.get("/auth/telegram", params=login_params(telegram_id=42, username="umer_new"))
    assert db.scalar(select(func.count()).select_from(User)) == 1
    db.refresh(user)
    assert user.username == "umer_new"
    assert user.telegram_status == TELEGRAM_CONNECTED


def test_forged_login_is_rejected(client, db):
    params = login_params()
    params["first_name"] = "Mallory"
    response = client.get("/auth/telegram", params=params, follow_redirects=False)
    assert response.headers["location"] == "/login?error=invalid"
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert "Telegram login couldn&#39;t be verified" in client.get("/login?error=invalid").text
    assert client.get("/stocks", follow_redirects=False).status_code == 303


def test_unknown_error_codes_are_not_echoed(client):
    html = client.get("/login", params={"error": "<script>alert(1)</script>"}).text
    assert "<script>alert(1)" not in html


def test_dev_login_is_off_by_default(client):
    assert client.post("/auth/dev-login").status_code == 404


def test_dev_login_signs_in_configured_telegram_id(make_client, db):
    client = make_client(dev_login=True, dev_telegram_id=555)
    assert "Dev login" in client.get("/login").text
    response = client.post("/auth/dev-login", follow_redirects=False)
    assert response.headers["location"] == "/stocks"
    assert db.scalar(select(User.telegram_id)) == 555


def test_dev_login_never_works_in_production(make_client):
    client = make_client(dev_login=True, app_env="production")
    assert client.post("/auth/dev-login").status_code == 404
    assert "Dev login" not in client.get("/login").text


def test_production_requires_a_real_secret_key():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_logout_ends_session(logged_in):
    response = logged_in.post("/logout", follow_redirects=False)
    assert response.headers["location"] == "/login"
    assert logged_in.get("/stocks", follow_redirects=False).status_code == 303


def test_railway_postgres_url_uses_psycopg_driver():
    settings = Settings(_env_file=None, database_url="postgres://u:p@host:5432/railway")
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@host:5432/railway"
    assert Settings(_env_file=None, database_url="sqlite:///x.db").sqlalchemy_url == "sqlite:///x.db"


def test_healthcheck(client):
    assert client.get("/healthz").text == "ok"
