"""Вход, выход и смена пароля. Регистрации нет: учётные записи создаёт
администратор, а при первом запуске появляются admin и employee."""
import hashlib
import logging
import threading
import time
from functools import wraps
from typing import Callable

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from storage.db import Database
from web.utils import audit, client_ip, get_db


bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

# Логин, пароль, имя, роль. Пароли нужно сменить после первого входа.
DEFAULT_ACCOUNTS = (
    ("admin", "admin", "Администратор", "admin"),
    ("employee", "employee", "Сотрудник", "employee"),
)
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
MAX_USERNAME_LENGTH = 32


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def check_password(password_hash: str | None, password: str) -> bool:
    return bool(password_hash) and check_password_hash(password_hash, password)


def session_token(user: dict) -> str:
    """Отпечаток пароля для сессии: после смены пароля сессии на других
    устройствах перестают действовать."""
    return hashlib.sha256(user["password_hash"].encode()).hexdigest()[:16]


def is_weak_password(username: str, password: str) -> bool:
    return (
        len(password) < MIN_PASSWORD_LENGTH
        or password.casefold() == username.casefold()
    )


def password_error(password: str, repeat: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Пароль должен быть не длиннее {MAX_PASSWORD_LENGTH} символов."
    if password != repeat:
        return "Пароли не совпадают."
    return None


def username_error(username: str) -> str | None:
    if not username:
        return "Укажите логин."
    if len(username) > MAX_USERNAME_LENGTH:
        return f"Логин должен быть не длиннее {MAX_USERNAME_LENGTH} символов."
    if not all(char.isalnum() or char in "._-" for char in username):
        return "В логине можно использовать буквы, цифры и символы . _ -"
    return None


def create_default_accounts(db: Database) -> None:
    """Создаёт admin/admin и employee/employee, если войти пока некому."""
    if db.has_login_users():
        return
    for username, password, full_name, role in DEFAULT_ACCOUNTS:
        if db.get_user_by_username(username) is None:
            db.add_user(username, full_name, hash_password(password), role)
    logger.warning(
        "Созданы учётные записи admin/admin и employee/employee — "
        "смените пароли после первого входа"
    )


class LoginLimiter:
    """Не даёт перебирать пароли: после MAX_FAILURES неудачных попыток
    вход с того же адреса под тем же логином закрыт на BLOCK_SECONDS."""

    MAX_FAILURES = 5
    BLOCK_SECONDS = 300

    def __init__(self) -> None:
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple[str, str], now: float) -> list[float]:
        attempts = [
            moment for moment in self._failures.get(key, [])
            if now - moment < self.BLOCK_SECONDS
        ]
        if attempts:
            self._failures[key] = attempts
        else:
            self._failures.pop(key, None)
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
            self._failures.setdefault(key, []).append(now)

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)


limiter = LoginLimiter()


def require_login():
    """before_request для разделов, куда пускают только после входа."""
    if g.user is None:
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    return None


def require_admin():
    """before_request для разделов администратора."""
    if g.user is not None and g.user["role"] != "admin":
        abort(403)
    return require_login()


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        return require_login() or view(*args, **kwargs)
    return wrapper


def _safe_next(target: str | None) -> str:
    """Возвращает только адрес этого сайта, чтобы ссылкой на вход нельзя
    было увести пользователя на чужой сайт."""
    if target and target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return url_for("main.dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = (client_ip() or "", username.casefold())
        db = get_db()

        wait = limiter.seconds_left(key)
        if wait:
            error = (
                "Слишком много неудачных попыток. Попробуйте через "
                f"{max(wait // 60, 1)} мин."
            )
        else:
            user = db.get_user_by_username(username) if username else None
            if user is None or not check_password(user["password_hash"], password):
                limiter.fail(key)
                db.log_action(
                    "login_failed", details=f"Логин: {username}"[:200],
                    ip=client_ip(),
                )
                error = "Неверный логин или пароль."
            elif not user["is_active"]:
                db.log_action(
                    "login_failed", details=f"Доступ отключён: {user['username']}",
                    user_id=user["id"], username=user["username"], ip=client_ip(),
                )
                error = "Доступ отключён. Обратитесь к администратору."
            else:
                limiter.reset(key)
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                session["auth"] = session_token(user)
                if is_weak_password(user["username"], password):
                    session["weak_password"] = True
                db.touch_last_login(user["id"])
                db.log_action(
                    "login", user_id=user["id"], username=user["username"],
                    ip=client_ip(),
                )
                return redirect(_safe_next(request.args.get("next")))

    return render_template("login.html", error=error, username=username)


@bp.post("/logout")
def logout():
    if g.user is not None:
        audit("logout")
    session.clear()
    flash("Вы вышли с сайта.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        repeat = request.form.get("repeat_password", "")
        error = password_error(new, repeat)
        if not check_password(g.user["password_hash"], current):
            error = "Текущий пароль указан неверно."
        elif error is None and is_weak_password(g.user["username"], new):
            error = "Пароль не должен совпадать с логином."

        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.set_user_password(g.user["id"], hash_password(new))
            g.user = db.get_user(g.user["id"])
            session["auth"] = session_token(g.user)
            session.pop("weak_password", None)
            audit("password_changed")
            flash("Пароль изменён.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html")
