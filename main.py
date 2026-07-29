import asyncio
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from telegram.handler import router


def get_bot_token() -> str:
    """Загружает токен Telegram-бота из переменных окружения."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "Переменная окружения TELEGRAM_BOT_TOKEN не задана"
        )

    return token


async def main() -> None:
    """Создаёт бота и запускает обработку входящих сообщений."""
    bot = Bot(token=get_bot_token())
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
