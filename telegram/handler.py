from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, keyboard_button,)


router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """Выводит основное меню."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="📦 Достать из заморозки 📦",
                    callback_data="defrost"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Сегодня заканчивается срок ⚠️",
                    callback_data="expired"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Списание и продажа 📈",
                    callback_data="white_sells"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Остатки 📊",
                    callback_data="white_sells"
                )
            ],

        ])
