"""Сайт учёта сроков годности: API на FastAPI и собранный фронтенд на Vue.

create_app() собирает приложение; запуск — python main.py.
"""
import logging
import secrets
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from api import admin, auth, logs, staff, tables
from storage.accounts import Accounts
from storage.db import Database


logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
SESSION_HOURS = 12
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

DEFAULT_SETTINGS = {
    "database": "data/database.db",
    "secret_key": None,
    "google_table": None,
    "credentials_file": "credentials.json",
    "log_file": "data/logs/app.log",
    "secure_cookies": False,
    "frontend_dist": FRONTEND_DIST,
}


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


def create_app(settings: dict | None = None) -> FastAPI:
    settings = {**DEFAULT_SETTINGS, **(settings or {})}
    db = Database(settings["database"])
    accounts = Accounts(db)
    if accounts.create_defaults():
        logger.warning("Созданы учётные записи admin/admin и employee/employee")
    secret_key = settings["secret_key"] or load_secret_key(
        Path(settings["database"]).parent / "secret_key"
    )

    app = FastAPI(title="Учёт сроков годности", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.accounts = accounts
    app.state.settings = settings

    # Только запросы со своей страницы: чужой сайт не может добавить
    # заголовок X-Requested-With без разрешения CORS, которого нет.
    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        if (
            request.method in UNSAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get("x-requested-with") != "XMLHttpRequest"
        ):
            return JSONResponse({"detail": "Запрос отклонён"}, status_code=403)
        return await call_next(request)

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="session",
        max_age=SESSION_HOURS * 3600,
        same_site="lax",
        https_only=settings["secure_cookies"],
    )

    for module in (auth, staff, admin, tables, logs):
        app.include_router(module.router, prefix="/api")

    _add_error_handlers(app, db)
    _add_frontend(app, Path(settings["frontend_dist"]))
    return app


def _who(request: Request) -> str:
    user_id = request.session.get("user_id") if "session" in request.scope else None
    return f"{request.method} {request.url.path}, сотрудник № {user_id}"


def _log_error(db: Database, error_type: str, message: str) -> None:
    try:
        db.log_error(error_type, message)
    except Exception:
        logger.exception("Не удалось записать ошибку в базу данных")


def _add_error_handlers(app: FastAPI, db: Database) -> None:
    """Все ошибки пишутся в таблицу errors и в журнал сервера.

    Не пишутся только «войдите на сайт» (401) и «нет такой страницы» (404):
    это не ошибки, а обычная работа сайта.
    """

    @app.exception_handler(ValueError)
    async def value_error(request: Request, error: ValueError):
        # Отказ базы или проверки: недостаточно товара, занятый логин и т.п.
        logger.warning("Отказ: %s (%s)", error, _who(request))
        _log_error(db, "ValueError", f"{error}\n{_who(request)}")
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        if error.status_code not in (401, 404):
            logger.warning("HTTP %s: %s (%s)", error.status_code, error.detail, _who(request))
            _log_error(db, f"HTTP {error.status_code}", f"{error.detail}\n{_who(request)}")
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"][1:]) or "запрос"
            for item in error.errors()
        )
        detail = f"Неверно заполнены поля: {fields}"
        _log_error(db, "RequestValidationError", f"{detail}\n{_who(request)}")
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(Exception)
    async def server_error(request: Request, error: Exception):
        logger.error("Ошибка при обработке %s", request.url.path, exc_info=error)
        _log_error(
            db, type(error).__name__,
            f"{_who(request)}\n" + "".join(traceback.format_exception(error)),
        )
        return JSONResponse(
            {"detail": "Что-то пошло не так. Ошибка записана в журнал."},
            status_code=500,
        )


def _add_frontend(app: FastAPI, dist: Path) -> None:
    """Собранный Vue: файлы из dist, остальные адреса — index.html."""
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Нет такого адреса")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(
            "<h1>Фронтенд не собран</h1><p>Выполните: <code>cd frontend && "
            "npm install && npm run build</code> и перезапустите сайт.</p>",
            status_code=503,
        )
