from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.states import DeliveryStates
from telegram.utils import (
    MAX_QUANTITY, PAGE_SIZE, SEARCH_LIMIT, esc, parse_ids, parse_positive_int,
    show,
)


# «❄️ Добавить заморозку»: поставка в морозильник из справочника товаров.
router = Router()

PRODUCT_GONE_TEXT = "Этого товара уже нет в справочнике."


def _product_items(products: list[dict]) -> list[tuple[str, str]]:
    return [
        (product["name"], f"delivery_product_{product['id']}")
        for product in products
    ]


def _deliver(
        db: Database,
        product_id: int,
        quantity: int,
        user_id: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
    """Добавляет товар в морозильник и возвращает текст ответа с кнопками."""
    product = db.get_product_by_id(product_id)
    if product is None:
        return PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("delivery")
    if quantity > MAX_QUANTITY:
        return (
            f"⚠️ Нельзя добавить больше {MAX_QUANTITY} шт. за раз.",
            ButtonBuilder.back_to_list("delivery"),
        )

    try:
        db.new_delivery(product["name"], quantity, user_id=user_id)
    except ValueError as error:
        return f"⚠️ {esc(error)}", ButtonBuilder.back_to_list("delivery")

    in_freezer = db.get_freezer_product(product["name"])
    total = in_freezer["quantity"] if in_freezer else quantity
    text = (
        "✅ <b>Добавлено в морозильник:</b>\n\n"
        f"{esc(product['name'])} — {quantity} шт\n\n"
        f"Теперь в морозильнике: {total} шт"
    )
    keyboard = ButtonBuilder.menu(
        [button("❄️ Добавить ещё", "delivery_page_1")]
    )
    return text, keyboard


@router.callback_query(F.data.startswith("delivery_page_"))
async def delivery_callback(
        callback: CallbackQuery,
        db: Database,
        is_admin: bool,
    ) -> None:
    """Справочник товаров по страницам."""
    ids = parse_ids(callback.data, "delivery_page_")
    page = ids[0] if ids else 1

    page_count, products = db.products_list(page=page, limit=PAGE_SIZE)
    if page_count is None:
        page = 1
        page_count, products = db.products_list(page=page, limit=PAGE_SIZE)

    if page_count == 0:
        hint = (
            "Добавьте товары в «⚙️ Настройки» → «📦 Товары»."
            if is_admin else
            "Попросите администратора добавить товары."
        )
        await show(
            callback,
            f"<b>Справочник товаров пуст.</b>\n\n{hint}",
            ButtonBuilder.menu(),
        )
        return

    await show(
        callback,
        "<b>Какой товар добавить в морозильник?</b>"
        f"    стр. {page}/{page_count}",
        ButtonBuilder.paginated(
            _product_items(products), "delivery", page, page_count
        ),
    )


@router.callback_query(F.data == "delivery_search")
async def delivery_search_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(DeliveryStates.search)
    await show(
        callback,
        "🔍 Введите часть названия товара:",
        ButtonBuilder.cancel(),
    )


@router.message(DeliveryStates.search, F.text)
async def delivery_search_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    query = message.text.strip()
    products = db.search_products(query, limit=SEARCH_LIMIT + 1)
    await state.clear()

    if not products:
        text = f"По запросу «{esc(query)}» товаров не найдено."
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
            _product_items(products[:SEARCH_LIMIT]), "delivery"
        ),
    )


@router.callback_query(F.data.startswith("delivery_product_"))
async def delivery_product_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Выбор количества для поставки."""
    ids = parse_ids(callback.data, "delivery_product_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("delivery"))
        return

    in_freezer = db.get_freezer_product(product["name"])
    current = in_freezer["quantity"] if in_freezer else 0
    await show(
        callback,
        f"<b>Вы выбрали товар:</b> {esc(product['name'])}\n"
        f"<b>Сейчас в морозильнике:</b> {current} шт.\n\n"
        "<b>Сколько добавить в морозильник?</b>",
        ButtonBuilder.quantity("delivery", product["id"]),
    )


@router.callback_query(F.data.startswith("delivery_count_"))
async def delivery_count_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "delivery_count_")
    if not ids or len(ids) != 2:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("delivery"))
        return

    product_id, quantity = ids
    text, keyboard = _deliver(db, product_id, quantity, callback.from_user.id)
    await show(callback, text, keyboard)


@router.callback_query(F.data.startswith("delivery_input_"))
async def delivery_input_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    """Ручной ввод количества."""
    ids = parse_ids(callback.data, "delivery_input_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, ButtonBuilder.back_to_list("delivery"))
        return

    await state.set_state(DeliveryStates.quantity)
    await state.update_data(product_id=product["id"])
    await show(
        callback,
        f"📝 Сколько <b>{esc(product['name'])}</b> добавить в морозильник?",
        ButtonBuilder.cancel(),
    )


@router.message(DeliveryStates.quantity, F.text)
async def delivery_quantity_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    data = await state.get_data()
    product = db.get_product_by_id(data.get("product_id", 0))
    if product is None:
        await state.clear()
        await message.answer(
            PRODUCT_GONE_TEXT, reply_markup=ButtonBuilder.back_to_list("delivery")
        )
        return

    quantity = parse_positive_int(message.text)
    if quantity is None:
        await message.answer(
            "Введите целое число больше нуля.",
            reply_markup=ButtonBuilder.cancel(),
        )
        return
    if quantity > MAX_QUANTITY:
        await message.answer(
            f"Слишком большое число. Введите не больше {MAX_QUANTITY}.",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    await state.clear()
    text, keyboard = _deliver(db, product["id"], quantity, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)
