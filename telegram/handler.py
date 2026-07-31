from email import message
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram import F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, keyboard_button,)

from storage.db import Database

router = Router()

class Maket:
    main_menu_buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="📦 Достать из заморозки 📦",
                    callback_data="defrost_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆕 Новая поставка 🆕",
                    callback_data="delivery"
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
                    callback_data="batches"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки ⚙️",
                    callback_data="settings"
                )
            ],
        ])


btns = Maket

@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """Выводит основное меню."""
    keyboard = btns.main_menu_buttons
    
    await message.answer(
        "*Выберите действие:*", reply_markup=keyboard
    )

@router.callback_query(F.data.startswith == "defrost")
async def defrost_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    keyboard = []

    page = int(callback.data.removeprefix("defrost_"))

    products = db.fridge_batches_list()

    await callback.message.edit_text()
