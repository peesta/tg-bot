from email import message
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram import F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, keyboard_button,)

from storage.db import Database

router = Router()

class ButtonBuilder:
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

    _page_idx = 0
    _page_count = 0

    async def increase_page_idx(self) -> None:
        self._page_idx += 1
        if self._page_idx > self._page_count:
            self._page_idx = 1

    async def decrease_page_idx(self) -> None:
        self._page_idx -= 1
        if self._page_idx < 1:
            self._page_idx = self._page_count

    async def reset_page(self) -> None:
        self._page_idx = 0
        self._page_count = 0

    async def get_page_count(self) -> int:
        return self._page_count

    async def get_page_idx(self) -> int:
        return self._page_idx

    async def defrost_buttons(self, page: int = 1, db: Database | None = None) -> InlineKeyboardMarkup:
        self._page_idx = page
        if page == 1:
            self._page_count, products = db.freezer_products_list()
        btns = [
                [
                    InlineKeyboardButton(
                        text="🔍 Поиск 🔎",
                        callback_data="search"
                    )
                ],
            ]
        if page > 1:
            btns.insert(0, [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back"
                )
            ])
        elif page < self._page_count:
            btns.append([
                InlineKeyboardButton(
                    text="Далее ➡️",
                    callback_data="next"
                )
            ])
        for i, product in enumerate(products):
            InlineKeyboardButton(
                text = f"{product['product_name']} - {product['quantity']} шт.",
                callback_data = f"defrost_{product['product_name']}"
            )

btns = ButtonBuilder()

@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """Выводит основное меню."""
    keyboard = btns.main_menu_buttons
    
    await message.answer(
        "*Выберите действие:*", reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("defrost_page_"))
async def defrost_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    page = int(callback.data.removeprefix("defrost_page_"))
    keyboard = await btns.defrost_buttons(page = page, db=db)
