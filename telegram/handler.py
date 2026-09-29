from email import message
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, keyboard_button,)

from storage.db import Database

router = Router()

class ButtonBuilder:
    main_menu_buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Достать из заморозки 📦",
                    callback_data="defrost_page_1"
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

    product_buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1",
                    callback_data="defrost_count_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="2",
                    callback_data="defrost_count_2"
                )
            ],
            [
                InlineKeyboardButton(
                    text="3",
                    callback_data="defrost_count_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Ввести число",
                    callback_data="defrost_count_self"
                )
            ],
        ])

    async def defrost_buttons(self, page: int | None = None, db: Database | None = None) -> tuple[int, int, InlineKeyboardMarkup]:

        if page is None or page < 1:
            page = 1

        page_count, products = db.freezer_products_list(page=page, limit = 3)

        if page_count == 0:
            return 0, 0, None
        elif page_count is None:
            return None, None, None
        if page > page_count:
            page = 1

        btns = [
                [
                    InlineKeyboardButton(
                        text="🔍 Поиск 🔎",
                        callback_data="defrost_search"
                    )
                ],
            ]
        if page > 1:
            btns.insert(0, [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"defrost_page_{page-1}"
                )
            ])
        if page < page_count:
            btns.append([
                InlineKeyboardButton(
                    text="Далее ➡️",
                    callback_data=f"defrost_page_{page+1}"
                )
            ])
        for i, product in enumerate(products):
            prod_btn = InlineKeyboardButton(
                text = f"{product['product_name']} - {product['quantity']} шт.",
                callback_data = f"defrost_product_{product['product_name']}"
            )
            btns.insert(i, [prod_btn])
        return page, page_count, InlineKeyboardMarkup(inline_keyboard=btns)



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
    try:
        page = int(callback.data.removeprefix("defrost_page_"))
    except ValueError:
        page = 1
    page, page_count, keyboard = await btns.defrost_buttons(page = page, db=db)

    if page_count == 0:
        await callback.message.edit_text(
            f"*В морозильнике нет продуктов.*", reply_markup=None
        )
        return
    elif page == None and page_count == None and keyboard == None:
        await callback.message.edit_text(
            f"*Некорректная страница.*", reply_markup=None
        )
        return

    await callback.message.edit_text(
            f"*Выберите продукт:    стр. {page}/{page_count}*", reply_markup=keyboard
        )

@router.callback_query(F.data.startswith("defrost_product_"))
async def defrost_product_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    product_name = callback.data.removeprefix("defrost_product_")
    product = db.get_freezer_product(product_name)
    if product is None:
        await callback.message.answer(
            f"Продукт {product_name} не найден."
        )
        return
    mess_text = f"""
        *Вы выбрали продукт:* {product_name}\n
        *Количество:* {product['quantity']} шт.\n\n
        *Сколько вы хотите разморозить?:*
        """
    keyboard = btns.product_buttons
    await callback.message.edit_text(
        text=mess_text,
        reply_markup=keyboard
    )
