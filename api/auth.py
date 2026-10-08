"""Вход, выход и смена своего пароля. Регистрации нет: сотрудников
добавляет администратор, при первом запуске есть admin и employee."""
import logging
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import current_user, get_accounts, public_user, session_token
from storage.accounts import Accounts, check_password, hash_password


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
    """Не даёт перебирать пароли. С одного адреса за BLOCK_SECONDS можно
    ошибиться MAX_FAILURES раз под одним логином и MAX_ADDRESS_FAILURES
    раз под всеми логинами вместе (иначе перебирают пароли по всем
    логинам подряд). Дальше вход с адреса закрыт, пока старые попытки
    не выйдут из окна."""

    MAX_FAILURES = 5
    MAX_ADDRESS_FAILURES = 20
    BLOCK_SECONDS = 300
    # Сколько записей хранить, прежде чем вычищать устаревшие.
    MAX_KEYS = 10_000

    def __init__(self) -> None:
        self.failures: dict[tuple, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple, now: float) -> list[float]:
        attempts = [
            moment for moment in self.failures.get(key, [])
            if now - moment < self.BLOCK_SECONDS
        ]
        if attempts:
            self.failures[key] = attempts
        else:
            self.failures.pop(key, None)
        return attempts

    def _wait(self, key: tuple, limit: int, now: float) -> int:
        attempts = self._recent(key, now)
        if len(attempts) < limit:
            return 0
        return int(self.BLOCK_SECONDS - (now - attempts[-limit])) + 1

    def seconds_left(self, ip: str, username: str) -> int:
        now = time.monotonic()
        with self._lock:
            return max(
                self._wait((ip, username), self.MAX_FAILURES, now),
                self._wait((ip,), self.MAX_ADDRESS_FAILURES, now),
            )

    def fail(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self.failures) > self.MAX_KEYS:
                for key in list(self.failures):
                    self._recent(key, now)
            for key in ((ip, username), (ip,)):
                self._recent(key, now)
                self.failures.setdefault(key, []).append(now)

    def reset(self, ip: str, username: str) -> None:
        """Удачный вход прощает ошибки под этим логином, но не общий счёт
        адреса: иначе его сбрасывали бы входом в свою учётную запись."""
        with self._lock:
            self.failures.pop((ip, username), None)


limiter = LoginLimiter()
# Для несуществующего логина пароль сверяется с этим хешем: ответ идёт
# столько же, сколько для настоящего, и по времени не понять, есть ли логин.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_hex(16))


@router.post("/auth/login")
def login(form: LoginForm, request: Request, accounts: Accounts = Depends(get_accounts)):
    username = form.username.strip()
    ip = request.client.host if request.client else ""
    login_key = username.casefold()

    wait = limiter.seconds_left(ip, login_key)
    if wait:
        raise HTTPException(
            429, f"Слишком много неудачных попыток. Попробуйте через {max(wait // 60, 1)} мин."
        )

    user = accounts.get_by_username(username) if username else None
    password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    if not check_password(password_hash, form.password) or user is None:
        limiter.fail(ip, login_key)
        logger.warning("Неудачный вход: логин %r, адрес %s", username, ip)
        raise HTTPException(401, "Неверный логин или пароль")
    if not user["is_active"]:
        logger.warning("Вход отключённого сотрудника %r, адрес %s", username, ip)
        raise HTTPException(403, "Доступ отключён. Обратитесь к администратору")

    limiter.reset(ip, login_key)
    accounts.delete_session(request.session.get("sid"))
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["auth"] = session_token(user)
    request.session["sid"] = accounts.create_session(user["id"])
    accounts.touch_login(user["id"])
    logger.info("Вход: %s (№ %s), адрес %s", user["username"], user["id"], ip)
    return public_user(user)


@router.post("/auth/logout")
def logout(request: Request, accounts: Accounts = Depends(get_accounts)):
    # Сессия удаляется из базы: сохранённая где-то копия cookie больше
    # не действует.
    accounts.delete_session(request.session.get("sid"))
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
