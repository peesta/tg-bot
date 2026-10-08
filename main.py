"""Запуск сайта учёта сроков годности.

    python main.py                       — запустить сайт
    python main.py set-password ЛОГИН    — задать пароль (если забыли)

Перед первым запуском соберите фронтенд: cd frontend && npm install && npm run build
"""
import argparse
import getpass
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from api import create_app
from api.auth import MIN_PASSWORD_LENGTH
from storage.accounts import Accounts
from storage.db import Database


DATABASE_PATH = "data/database.db"
LOG_FILE = "data/logs/app.log"
FRONTEND_INDEX = Path(__file__).resolve().parent / "frontend" / "dist" / "index.html"
TRUE_VALUES = ("1", "true", "yes", "on", "да")
ALL_ADDRESSES = ("0.0.0.0", "::")


def get_settings() -> dict:
    """Читает настройки сайта из .env и переменных окружения."""
    load_dotenv()
    port_text = os.getenv("PORT", "8000").strip() or "8000"
    if not port_text.isdigit() or not 0 < int(port_text) < 65536:
        raise RuntimeError(f"PORT: «{port_text}» — нужен номер порта от 1 до 65535")

    return {
        "host": os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1",
        "port": int(port_text),
        "secret_key": os.getenv("SECRET_KEY", "").strip() or None,
        "google_table": os.getenv("GOOGLE_TABLE", "").strip() or None,
        "secure_cookies": os.getenv("SECURE_COOKIES", "").strip().lower() in TRUE_VALUES,
    }


def local_ip() -> str | None:
    """Адрес компьютера в локальной сети (пакеты при этом не отправляются)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
    except OSError:
        return None


def site_links(host: str, port: int) -> list[str]:
    """Ссылки, по которым открыть сайт после запуска."""
    if host not in ALL_ADDRESSES:
        return [f"http://{host}:{port}"]
    links = [f"http://127.0.0.1:{port}"]
    ip = local_ip()
    if ip and not ip.startswith("127."):
        links.append(f"http://{ip}:{port}   (с планшета в той же сети)")
    return links


def setup_logging(log_file: str) -> None:
    """Журнал в консоль и в файл — его показывает раздел «Логи»."""
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"),
        ],
        force=True,
    )


def set_password(username: str, db_path: str = DATABASE_PATH) -> None:
    """Задаёт пароль и включает доступ; если логина нет — создаёт
    администратора. Нужен, если единственный администратор забыл пароль."""
    db = Database(db_path)
    accounts = Accounts(db)
    password = getpass.getpass(f"Новый пароль для {username}: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if getpass.getpass("Повторите пароль: ") != password:
        raise SystemExit("Пароли не совпадают")

    user = accounts.get_by_username(username)
    if user is None:
        accounts.create_user(username, username, password, "admin")
        print(f"Создан администратор {username}")
        return
    accounts.set_password(user["id"], password)
    if not user["is_active"]:
        db.set_user_active(user["id"], True)
    print(f"Пароль для {user['username']} изменён, доступ включён")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Сайт учёта сроков годности")
    commands = parser.add_subparsers(dest="command")
    password_parser = commands.add_parser("set-password", help="задать пароль сотруднику")
    password_parser.add_argument("username", help="логин")
    args = parser.parse_args(argv)

    if args.command == "set-password":
        set_password(args.username)
        return

    settings = get_settings()
    setup_logging(LOG_FILE)
    app = create_app({
        "database": DATABASE_PATH,
        "log_file": LOG_FILE,
        "secret_key": settings["secret_key"],
        "google_table": settings["google_table"],
        "secure_cookies": settings["secure_cookies"],
    })
    if settings["google_table"] is None:
        logging.warning("GOOGLE_TABLE не задан: экспорт и импорт Google Таблицы работать не будут")
    if not FRONTEND_INDEX.is_file():
        logging.warning(
            "Фронтенд не собран — вместо сайта будет подсказка. "
            "Выполните: cd frontend && npm install && npm run build"
        )
    links = "\n".join(f"    {link}" for link in site_links(settings["host"], settings["port"]))
    logging.info("Сайт запускается. Откройте в браузере:\n%s\nОстановить: Ctrl+C", links)
    uvicorn.run(app, host=settings["host"], port=settings["port"], log_config=None)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        sys.exit(f"Ошибка настройки: {error}")
