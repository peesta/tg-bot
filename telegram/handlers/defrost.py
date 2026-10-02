from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.states import DefrostStates
from telegram.utils import (
    PAGE_SIZE, SEARCH_LIMIT, esc, format_date, parse_ids, parse_positive_int,
    show,
)


router = Router()

PRODUCT_GONE_TEXT = "Этого продукта уже нет в морозильнике."


def _freezer_items(products: list[dict]) -> list[tuple[str, str]]:
    return [
        (
            f"{product['product_name']} - {product['quantity']} шт.",
            f"defrost_product_{product['id']}",
        )
        for product in products
    ]


def _defrost(
        db: Database,
        product_id: int,
        quantity: int,
        user_id: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
    """Размораживает продукт и возвращает текст ответа с кнопками."""
    product = db.get_freezer_product_by_id(product_id)
    if product is None:
        return PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("defrost")

    try:
        batch = db.move_to_fridge(
            product["product_name"], quantity, user_id=user_id
        )
    except ValueError as error:
        return f"⚠️ {esc(error)}", ButtonBuilder.back_to_list("defrost")

    text = (
        "✅ <b>Добавлено:</b>\n\n"
        f"{esc(batch['product_name'])} — {batch['quantity']} шт\n\n"
        "<b>Дата разморозки:</b>\n"
        f"{datetime.now():%d.%m.%Y %H:%M}\n\n"
        "<b>Годен до:</b>\n"
        f"{format_date(batch['expiration_date'])}"
    )
    keyboard = ButtonBuilder.menu(
        [button("📦 Разморозить ещё", "defrost_page_1")]
    )
    return text, keyboard


@router.callback_query(F.data.startswith("defrost_page_"))
async def defrost_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Список продуктов морозильника по страницам."""
    ids = parse_ids(callback.data, "defrost_page_")
    page = ids[0] if ids else 1

    page_count, products = db.freezer_products_list(page=page, limit=PAGE_SIZE)
    if page_count is None:
        # Страницы уже нет, например после разморозки последнего продукта.
        page = 1
        page_count, products = db.freezer_products_list(page=page, limit=PAGE_SIZE)

    if page_count == 0:
        await show(
            callback,
            "<b>В морозильнике нет продуктов.</b>\n\n"
            "Добавьте их кнопкой «❄️ Добавить заморозку».",
            ButtonBuilder.menu(),
        )
        return

    await show(
        callback,
        f"<b>Выберите продукт:</b>    стр. {page}/{page_count}",
        ButtonBuilder.paginated(
            _freezer_items(products), "defrost", page, page_count
        ),
    )


@router.callback_query(F.data == "defrost_search")
async def defrost_search_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(DefrostStates.search)
    await show(
        callback,
        "🔍 Введите часть названия продукта:",
        ButtonBuilder.cancel(),
    )


@router.message(DefrostStates.search, F.text)
async def defrost_search_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    query = message.text.strip()
    products = db.search_freezer_products(query, limit=SEARCH_LIMIT + 1)
    await state.clear()

    if not products:
        text = f"По запросу «{esc(query)}» в морозильнике ничего не найдено."
    elif len(products) > SEARCH_LIMIT:
        text = (
            f"<b>Найдено по запросу «{esc(query)}»:</b>\n"
            f"Показаны первые {SEARCH_LIMIT}, уточните запрос."
        )
    else:
        text = f"<b>Найдено по запросу «{esc(query)}»:</b>"

    await message.answer(
        text,
        reply_markup=ButtonBuilder.search_results(
            _freezer_items(products[:SEARCH_LIMIT]), "defrost"
        ),
    )


@router.callback_query(F.data.startswith("defrost_product_"))
async def defrost_product_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Выбор количества для разморозки."""
    ids = parse_ids(callback.data, "defrost_product_")
    product = db.get_freezer_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("defrost"))
        return

    mess_text = (
        f"<b>Вы выбрали продукт:</b> {esc(product['product_name'])}\n"
        f"<b>Количество:</b> {product['quantity']} шт.\n\n"
        "<b>Сколько вы хотите разморозить?</b>"
    )
    await show(
        callback,
        mess_text,
        ButtonBuilder.quantity("defrost", product["id"], product["quantity"]),
    )


@router.callback_query(F.data.startswith("defrost_count_"))
async def defrost_count_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "defrost_count_")
    if not ids or len(ids) != 2:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("defrost"))
        return

    product_id, quantity = ids
    text, keyboard = _defrost(db, product_id, quantity, callback.from_user.id)
    await show(callback, text, keyboard)


@router.callback_query(F.data.startswith("defrost_input_"))
async def defrost_input_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    """Ручной ввод количества."""
    ids = parse_ids(callback.data, "defrost_input_")
    product = db.get_freezer_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("defrost"))
        return

    await state.set_state(DefrostStates.quantity)
    await state.update_data(product_id=product["id"])
    await show(
        callback,
        f"📝 Введите количество <b>{esc(product['product_name'])}</b> "
        f"(в морозильнике {product['quantity']} шт.):",
        ButtonBuilder.cancel(),
    )


@router.message(DefrostStates.quantity, F.text)
async def defrost_quantity_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    data = await state.get_data()
    product = db.get_freezer_product_by_id(data.get("product_id", 0))
    if product is None:
        await state.clear()
        await message.answer(
            PRODUCT_GONE_TEXT, reply_markup=ButtonBuilder.back_to_list("defrost")
        )
        return

    quantity = parse_positive_int(message.text)
    if quantity is None:
        await message.answer(
            "Введите целое число больше нуля.",
            reply_markup=ButtonBuilder.cancel(),
        )
        return
    if quantity > product["quantity"]:
        await message.answer(
            f"В морозильнике только {product['quantity']} шт. "
            "Введите число не больше остатка.",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    await state.clear()
    text, keyboard = _defrost(db, product["id"], quantity, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)
