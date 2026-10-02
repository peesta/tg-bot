"""Запуск сайта учёта сроков годности.

    python main.py                       — запустить сайт
    python main.py --debug               — запустить с автоперезагрузкой
    python main.py set-password ЛОГИН    — задать пароль (если забыли)
"""
import argparse
import getpass
import logging
import os
import sys

from dotenv import load_dotenv
from waitress import serve

from storage.db import Database
from web import create_app, setup_logging
from web.auth import MIN_PASSWORD_LENGTH, hash_password


DATABASE_PATH = "data/database.db"
LOG_FILE = "data/logs/app.log"
TRUE_VALUES = ("1", "true", "yes", "on", "да")


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
        "secure_cookies": (
            os.getenv("SECURE_COOKIES", "").strip().lower() in TRUE_VALUES
        ),
    }


def set_password(username: str, db_path: str = DATABASE_PATH) -> None:
    """Задаёт пароль и включает доступ; если логина нет — создаёт
    администратора. Нужен, если единственный администратор забыл пароль."""
    db = Database(db_path)
    password = getpass.getpass(f"Новый пароль для {username}: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if getpass.getpass("Повторите пароль: ") != password:
        raise SystemExit("Пароли не совпадают")

    user = db.get_user_by_username(username)
    if user is None:
        db.add_user(username, username, hash_password(password), "admin")
        print(f"Создан администратор {username}")
    else:
        db.set_user_password(user["id"], hash_password(password))
        db.set_user_active(user["id"], True)
        print(f"Пароль для {user['username']} изменён, доступ включён")
    db.log_action("user_updated", f"{username}: пароль задан из командной строки")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Сайт учёта сроков годности")
    parser.add_argument(
        "--debug", action="store_true",
        help="режим разработки: автоперезагрузка и подробные ошибки",
    )
    commands = parser.add_subparsers(dest="command")
    password_parser = commands.add_parser(
        "set-password", help="задать пароль пользователю"
    )
    password_parser.add_argument("username", help="логин")
    args = parser.parse_args(argv)

    if args.command == "set-password":
        set_password(args.username)
        return

    settings = get_settings()
    setup_logging(LOG_FILE)
    app = create_app({
        "DATABASE": DATABASE_PATH,
        "LOG_FILE": LOG_FILE,
        "SECRET_KEY": settings["secret_key"],
        "GOOGLE_TABLE": settings["google_table"],
        "SESSION_COOKIE_SECURE": settings["secure_cookies"],
    })
    if settings["google_table"] is None:
        logging.warning(
            "GOOGLE_TABLE не задан: экспорт и импорт Google Таблицы "
            "работать не будут"
        )

    logging.info(
        "Сайт запущен: http://%s:%s", settings["host"], settings["port"]
    )
    if args.debug:
        app.run(host=settings["host"], port=settings["port"], debug=True)
    else:
        serve(app, host=settings["host"], port=settings["port"], threads=8)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        sys.exit(f"Ошибка настройки: {error}")
