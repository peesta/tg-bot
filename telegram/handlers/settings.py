from aiogram import F, Router
from aiogram.types import CallbackQuery

from telegram.keyboards import ButtonBuilder
from telegram.middlewares import IsAdmin
from telegram.utils import show


# «⚙️ Настройки». Только администратор.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "settings")
async def settings_callback(callback: CallbackQuery) -> None:
    await show(callback, "⚙️ <b>Настройки</b>", ButtonBuilder.settings())
