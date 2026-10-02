"""Сайт учёта сроков годности: замена Telegram-бота.

create_app() собирает приложение Flask; запуск — python main.py.
"""
import logging
import secrets
import traceback
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, g, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException, InternalServerError

from storage.db import Database
from web import admin, auth, database, logs, staff
from web.utils import (
    ACTION_TITLES, OPERATION_TITLES, ROLE_TITLES, batch_status, format_date,
    format_datetime, get_db, sum_by_product, today,
)


logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(log_file: str) -> None:
    """Пишет лог в консоль и в файл (его показывает раздел «Логи»)."""
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(), file_handler],
        force=True,
    )


def load_secret_key(path: Path) -> str:
    """Ключ подписи сессий из файла; при первом запуске создаёт его.

    Без постоянного ключа после перезапуска всех выкидывало бы с сайта.
    """
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    path.chmod(0o600)
    return key


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE="data/database.db",
        SECRET_KEY=None,
        GOOGLE_TABLE=None,
        CREDENTIALS_FILE="credentials.json",
        LOG_FILE="data/logs/app.log",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=1_000_000,
    )
    app.config.update(config or {})

    db = Database(app.config["DATABASE"])
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = load_secret_key(
            Path(app.config["DATABASE"]).parent / "secret_key"
        )
    app.extensions["db"] = db
    auth.create_default_accounts(db)

    for blueprint in (auth.bp, staff.bp, admin.bp, database.bp, logs.bp):
        app.register_blueprint(blueprint)

    app.before_request(_load_user)
    app.before_request(_check_csrf)
    app.before_request(_daily_notice)
    app.after_request(_security_headers)
    app.context_processor(_template_context)
    app.register_error_handler(HTTPException, _http_error)
    app.register_error_handler(InternalServerError, _server_error)

    # Глобальные функции видны и в макросах, импортированных из _macros.html.
    app.jinja_env.globals.update(csrf_token=csrf_token, url_with=url_with)
    app.jinja_env.filters.update(
        date=format_date,
        datetime=format_datetime,
        status=batch_status,
        operation=lambda value: OPERATION_TITLES.get(value, value),
        action=lambda value: ACTION_TITLES.get(value, value),
        role=lambda value: ROLE_TITLES.get(value, value),
    )
    return app


def _load_user() -> None:
    """Пользователь из сессии. Отключённого или сменившего пароль
    пользователя сразу выкидывает с сайта."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = get_db().get_user(user_id)
    if (
        user is not None
        and user["is_active"]
        and user["password_hash"]
        and secrets.compare_digest(session.get("auth", ""), auth.session_token(user))
    ):
        g.user = user
    else:
        session.clear()


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _check_csrf():
    """Каждая форма несёт токен из сессии: чужой сайт не сможет отправить
    форму от имени вошедшего пользователя."""
    if request.method != "POST":
        return None
    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
        return render_template(
            "error.html",
            code=400,
            title="Страница устарела",
            message="Обновите страницу и повторите действие.",
        ), 400
    return None


def _daily_notice() -> None:
    """После первого за день открытия сайта показывает продукты с
    истекающим сроком — как уведомление бота в начале смены.

    Не показывается, если первым делом открыт «Сегодня заканчивается срок»:
    там тот же список.
    """
    if g.user is None or request.method != "GET" or request.endpoint == "static":
        return
    db = get_db()
    if not db.mark_daily_notification(g.user["id"], today()):
        return
    if request.endpoint == "main.expiring":
        return
    result = db.get_expiring_products()
    if result:
        expired, expiring_today = result
        session["expiring_notice"] = {
            "today": sum_by_product(expiring_today),
            "expired": sum_by_product(expired),
        }


def _security_headers(response):
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'",
    )
    return response


def url_with(**changes) -> str:
    """Адрес текущей страницы с изменёнными параметрами (None убирает
    параметр): для листания страниц и сортировки."""
    args = request.args.to_dict()
    for name, value in changes.items():
        if value is None:
            args.pop(name, None)
        else:
            args[name] = value
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def _template_context() -> dict:
    context = {
        "user": g.get("user"),
        "today_iso": today(),
    }
    if g.get("user") is not None:
        result = get_db().get_expiring_products()
        context["expiring_count"] = len(result[0]) + len(result[1]) if result else 0
        context["is_admin"] = g.user["role"] == "admin"
        context["expiring_notice"] = session.pop("expiring_notice", None)
        context["weak_password"] = session.get("weak_password", False)
    return context


def _http_error(error: HTTPException):
    titles = {
        400: "Неверный запрос",
        403: "Нет доступа",
        404: "Страница не найдена",
        405: "Действие недоступно",
    }
    messages = {
        403: "Этот раздел доступен только администратору.",
        404: "Возможно, ссылка устарела.",
    }
    return render_template(
        "error.html",
        code=error.code,
        title=titles.get(error.code, error.name),
        message=messages.get(error.code, ""),
    ), error.code


def _server_error(error: InternalServerError):
    """Пишет ошибку в лог и в таблицу errors, показывает понятную страницу."""
    exception = error.original_exception or error
    logger.error("Ошибка при обработке %s", request.path, exc_info=exception)
    try:
        get_db().log_error(
            type(exception).__name__,
            f"{request.method} {request.path}\n"
            + "".join(traceback.format_exception(exception)),
        )
    except Exception:
        logger.exception("Не удалось записать ошибку в базу данных")
    return render_template(
        "error.html",
        code=500,
        title="Что-то пошло не так",
        message="Ошибка записана в лог. Попробуйте ещё раз.",
    ), 500
