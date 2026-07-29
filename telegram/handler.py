from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message


router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """Подтверждает пользователю успешный запуск бота."""
    await message.answer("Бот запущен.")
