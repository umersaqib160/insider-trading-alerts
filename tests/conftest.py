import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.main import create_app
from app.models import Company, Politician
from app.web import get_telegram

BOT_TOKEN = "123456:TEST-TOKEN"
FIXTURES = Path(__file__).parent / "fixtures"
HX = {"HX-Request": "true"}


def sign(params: dict, token: str = BOT_TOKEN) -> dict:
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hashlib.sha256(token.encode()).digest()
    return {**params, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}


def login_params(telegram_id: int = 42, **extra: str) -> dict:
    params = {"id": str(telegram_id), "first_name": "Umer", "username": "umer", "auth_date": str(int(time.time()))}
    params.update(extra)
    return sign(params)


def toast_of(response) -> str:
    return json.loads(response.headers["HX-Trigger"])["showToast"]["message"]


def make_settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite://",
        "secret_key": "test-secret",
        "telegram_bot_token": BOT_TOKEN,
        "telegram_bot_username": "btc_test_bot",
        "dev_login": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeTelegram:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.error: Exception | None = None

    def send_message(self, chat_id: int, text: str) -> None:
        if self.error:
            raise self.error
        self.sent.append((chat_id, text))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def make_client(db, telegram):
    def _make(**overrides) -> TestClient:
        app = create_app(make_settings(**overrides))
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_telegram] = lambda: telegram
        return TestClient(app)
    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def logged_in(client) -> TestClient:
    response = client.get("/auth/telegram", params=login_params(), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/stocks"
    return client


@pytest.fixture
def seeded(db):
    db.add_all([
        Company(ticker="AAPL", name="Apple Inc.", sector="Information Technology", industry="Technology Hardware",
                cik="0000320193", exchange="Nasdaq", in_sp500=True),
        Company(ticker="NVDA", name="Nvidia", sector="Information Technology", industry="Semiconductors",
                cik="0001045810", exchange="Nasdaq", in_sp500=True),
        Company(ticker="XOM", name="Exxon Mobil", sector="Energy", industry="Integrated Oil & Gas",
                cik="0000034088", exchange="NYSE", in_sp500=True),
        Company(ticker="LMT", name="Lockheed Martin", sector="Industrials", industry="Aerospace & Defense",
                cik="0000936468", exchange="NYSE", in_sp500=True),
        Company(ticker="SMCO", name="Small Co", sector="Industrials", industry="Machinery", cik="0000000777",
                exchange="Nasdaq"),
        Company(ticker="GONE", name="Departed Co", sector="Energy", listed=False),
    ])
    db.add_all([
        Politician(bioguide_id="C000127", full_name="Maria Cantwell", first_name="Maria", last_name="Cantwell",
                   chamber="senate", party="D", state="WA", committees=["Commerce, Science, and Transportation", "Intelligence"],
                   led_committees=["Commerce, Science, and Transportation"]),
        Politician(bioguide_id="B001236", full_name="John Boozman", first_name="John", last_name="Boozman",
                   chamber="senate", party="R", state="AR", committees=["Armed Services"]),
        Politician(bioguide_id="P000197", full_name="Nancy Pelosi", first_name="Nancy", last_name="Pelosi",
                   chamber="house", party="D", state="CA", district=11, committees=[]),
    ])
    db.commit()
