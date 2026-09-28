from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import TELEGRAM_CONNECTED, User, utcnow
from .telegram import TelegramLogin

SESSION_USER_KEY = "uid"


class LoginRequired(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        request.session.clear()
        raise LoginRequired()
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    return db.get(User, user_id) if isinstance(user_id, int) else None


def log_in(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def upsert_telegram_user(db: Session, login: TelegramLogin) -> User:
    user = db.scalar(select(User).where(User.telegram_id == login.id))
    if user is None:
        user = User(telegram_id=login.id)
        db.add(user)
    user.first_name = login.first_name
    user.last_name = login.last_name
    user.username = login.username
    user.photo_url = login.photo_url
    # A fresh Telegram login with write access means the bot may message the user again.
    user.telegram_status = TELEGRAM_CONNECTED
    user.last_login_at = utcnow()
    db.commit()
    return user
