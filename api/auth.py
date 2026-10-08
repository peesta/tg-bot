"""Вход, выход и смена своего пароля. Регистрации нет: сотрудников
добавляет администратор, при первом запуске есть admin и employee."""
import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import current_user, get_accounts, public_user, session_token
from storage.accounts import Accounts, check_password


router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 128


class LoginForm(BaseModel):
    username: str
    password: str


class PasswordForm(BaseModel):
    current_password: str
    new_password: str


def password_error(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Пароль должен быть не длиннее {MAX_PASSWORD_LENGTH} символов"
    return None


class LoginLimiter:
    """Не даёт перебирать пароли: после MAX_FAILURES неудачных попыток
    вход с того же адреса под тем же логином закрыт на BLOCK_SECONDS."""

    MAX_FAILURES = 5
    BLOCK_SECONDS = 300

    def __init__(self) -> None:
        self.failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple[str, str], now: float) -> list[float]:
        attempts = [
            moment for moment in self.failures.get(key, [])
            if now - moment < self.BLOCK_SECONDS
        ]
        if attempts:
            self.failures[key] = attempts
        else:
            self.failures.pop(key, None)
        return attempts

    def seconds_left(self, key: tuple[str, str]) -> int:
        now = time.monotonic()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.MAX_FAILURES:
                return 0
            return int(self.BLOCK_SECONDS - (now - attempts[0])) + 1

    def fail(self, key: tuple[str, str]) -> None:
        now = time.monotonic()
        with self._lock:
            self._recent(key, now)
            self.failures.setdefault(key, []).append(now)

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self.failures.pop(key, None)


limiter = LoginLimiter()


@router.post("/auth/login")
def login(form: LoginForm, request: Request, accounts: Accounts = Depends(get_accounts)):
    username = form.username.strip()
    ip = request.client.host if request.client else ""
    key = (ip, username.casefold())

    wait = limiter.seconds_left(key)
    if wait:
        raise HTTPException(
            429, f"Слишком много неудачных попыток. Попробуйте через {max(wait // 60, 1)} мин."
        )

    user = accounts.get_by_username(username) if username else None
    if user is None or not check_password(user["password_hash"], form.password):
        limiter.fail(key)
        logger.warning("Неудачный вход: логин %r, адрес %s", username, ip)
        raise HTTPException(401, "Неверный логин или пароль")
    if not user["is_active"]:
        logger.warning("Вход отключённого сотрудника %r, адрес %s", username, ip)
        raise HTTPException(403, "Доступ отключён. Обратитесь к администратору")

    limiter.reset(key)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["auth"] = session_token(user)
    accounts.touch_login(user["id"])
    logger.info("Вход: %s (№ %s), адрес %s", user["username"], user["id"], ip)
    return public_user(user)


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


@router.post("/auth/password")
def change_password(
    form: PasswordForm,
    request: Request,
    user: dict = Depends(current_user),
    accounts: Accounts = Depends(get_accounts),
):
    if not check_password(user["password_hash"], form.current_password):
        raise ValueError("Текущий пароль указан неверно")
    error = password_error(form.new_password)
    if error:
        raise ValueError(error)
    accounts.set_password(user["id"], form.new_password, changed_by=user["id"])
    # Текущая сессия продолжает работать, остальные — сбрасываются.
    request.session["auth"] = session_token(accounts.get(user["id"]))
    return {"ok": True}
