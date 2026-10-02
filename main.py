import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv

from telegram.handler import router
from storage.db import Database


BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
    BotCommand(command="id", description="Мой Telegram ID"),
]


def get_bot_token() -> str:
    """Загружает токен Telegram-бота (TELEGRAM_KEY) из переменных окружения."""
    load_dotenv()
    token = os.getenv("TELEGRAM_KEY", "").strip()

    if not token:
        raise RuntimeError(
            "Переменная окружения TELEGRAM_KEY не задана: добавьте в .env "
            "токен бота от @BotFather"
        )

    try:
        validate_token(token)
    except TokenValidationError:
        raise RuntimeError(
            "TELEGRAM_KEY не похож на токен бота: он должен выглядеть как "
            "123456789:AAH..., без пробелов и кавычек"
        ) from None

    return token


def get_admin_ids() -> frozenset[int]:
    """Загружает ADMIN_IDS — Telegram ID администраторов через запятую.

    Они всегда имеют доступ к боту, даже если их нет в таблице users.
    Так появляется первый администратор, который добавит остальных.
    """
    load_dotenv()
    admin_ids = set()

    for part in os.getenv("ADMIN_IDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise RuntimeError(
                f"ADMIN_IDS: «{part}» не похоже на Telegram ID"
            )
        admin_ids.add(int(part))

    return frozenset(admin_ids)


def get_google_table() -> str | None:
    """Загружает GOOGLE_TABLE — ссылку на Google Таблицу или её ID."""
    load_dotenv()
    return os.getenv("GOOGLE_TABLE", "").strip() or None


async def main() -> None:
    """Создаёт бота и запускает обработку входящих сообщений."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    db = Database("data/database.db")
    admin_ids = get_admin_ids()
    if not admin_ids:
        logging.warning(
            "ADMIN_IDS не задан: в бота попадут только пользователи из "
            "таблицы users"
        )

    google_table = get_google_table()
    if google_table is None:
        logging.warning(
            "GOOGLE_TABLE не задан: экспорт и импорт Google Таблицы "
            "работать не будут"
        )

    dispatcher = Dispatcher(
        db=db, admin_ids=admin_ids, google_table=google_table
    )
    dispatcher.include_router(router)

    await bot.set_my_commands(BOT_COMMANDS)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
