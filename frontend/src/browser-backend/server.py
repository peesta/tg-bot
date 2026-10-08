"""FastAPI-сайт внутри браузера (Pyodide) — для Cloudflare Pages.

Тот же код из api/ и storage/, что и у python main.py, но без сервера:
worker.js передаёт сюда запросы фронтенда, а ответы возвращает обратно.
База SQLite лежит в /data — эту папку worker.js хранит в IndexedDB
браузера, поэтому у каждого посетителя своя база.
"""
import asyncio
import hashlib
import json
import logging
import sys
import types
from http.cookies import SimpleCookie
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

import anyio.to_thread


DATA_DIR = Path("/data")
COOKIES_FILE = DATA_DIR / "cookies.json"


# Потоков в браузере нет: синхронные обработчики FastAPI выполняем сразу.
async def _run_sync(func, *args, abandon_on_cancel=False, cancellable=None, limiter=None):
    return func(*args)


anyio.to_thread.run_sync = _run_sync


def _scrypt(password, *, salt, n, r, p, maxmem=0, dklen=64):
    """hashlib.scrypt без OpenSSL (его нет в Pyodide): тот же алгоритм на JS,
    хеши паролей совпадают с серверной версией сайта."""
    from browser_crypto import scrypt
    from pyodide.ffi import to_js
    return scrypt(to_js(bytes(password)), to_js(bytes(salt)), n, r, p, dklen).to_bytes()


if not hasattr(hashlib, "scrypt"):
    hashlib.scrypt = _scrypt


class _Missing(types.ModuleType):
    """Заглушка для gspread и Google: в браузере Google Таблица недоступна,
    но storage/google_sheets.py импортирует эти модули при загрузке."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name[0].isupper():
            value = type(name, (Exception,), {})
        else:
            value = _Missing(f"{self.__name__}.{name}")
        setattr(self, name, value)
        return value


for _name in ("gspread", "google", "google.auth", "google.auth.exceptions",
              "requests", "requests.exceptions"):
    sys.modules.setdefault(_name, _Missing(_name))

from api import create_app  # noqa: E402  (после заглушек)


app = None
cookies: dict[str, str] = {}


def start() -> None:
    global app
    log_file = DATA_DIR / "logs" / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")],
        force=True,
    )
    app = create_app({
        "database": str(DATA_DIR / "database.db"),
        "log_file": str(log_file),
    })
    load_cookies()
    logging.info("Сайт запущен в браузере")


def load_cookies() -> None:
    cookies.clear()
    try:
        cookies.update(json.loads(COOKIES_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _remember_cookies(header_values: list[str]) -> None:
    changed = False
    for value in header_values:
        jar = SimpleCookie()
        jar.load(value)
        for name, morsel in jar.items():
            if morsel["max-age"] == "0" or "1970" in morsel["expires"]:
                changed |= cookies.pop(name, None) is not None
            else:
                cookies[name] = morsel.value
                changed = True
    if changed:
        COOKIES_FILE.write_text(json.dumps(cookies), encoding="utf-8")


async def handle(method: str, url: str, headers_json: str, body: str | None) -> dict:
    """Один запрос к сайту, как его отправил бы браузер."""
    parts = urlsplit(url)
    headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in json.loads(headers_json).items()
    ]
    if cookies:
        cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
        headers.append((b"cookie", cookie.encode("latin-1")))
    payload = (body or "").encode("utf-8")
    headers.append((b"content-length", str(len(payload)).encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "https",
        "path": unquote(parts.path),
        "raw_path": parts.path.encode("latin-1"),
        "query_string": parts.query.encode("latin-1"),
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 443),
    }
    finished = asyncio.Event()
    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await finished.wait()
        return {"type": "http.disconnect"}

    response = {"status": 500, "headers": [], "body": bytearray()}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status"] = message["status"]
            response["headers"] = [
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in message.get("headers", [])
            ]
        elif message["type"] == "http.response.body":
            response["body"] += message.get("body", b"")

    try:
        await app(scope, receive, send)
    finally:
        finished.set()

    _remember_cookies([value for name, value in response["headers"] if name == "set-cookie"])
    return {
        "status": response["status"],
        "headers": {name: value for name, value in response["headers"] if name != "set-cookie"},
        "body": bytes(response["body"]),
    }
