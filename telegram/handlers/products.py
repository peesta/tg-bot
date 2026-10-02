from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.middlewares import IsAdmin
from telegram.states import ProductStates
from telegram.utils import (
    MAX_NAME_LENGTH, MAX_STORAGE_DAYS, PAGE_SIZE, SEARCH_LIMIT, clean_name,
    esc, parse_ids, parse_positive_int, show,
)


# «⚙️ Настройки» → «📦 Товары»: справочник товаров. Только администратор.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PRODUCT_GONE_TEXT = "Этого товара уже нет в справочнике."
STORAGE_DAYS_ERROR = (
    f"Введите количество дней — целое число от 1 до {MAX_STORAGE_DAYS}."
)


def _product_items(products: list[dict]) -> list[tuple[str, str]]:
    return [
        (
            f"{product['name']} — {product['fridge_storage_time']} дн.",
            f"prod_view_{product['id']}",
        )
        for product in products
    ]


def _back_to_products() -> InlineKeyboardMarkup:
    return ButtonBuilder.menu([button("⬅️ К товарам", "prod_page_1")])


def _product_card(db: Database, product: dict) -> str:
    in_freezer = db.get_freezer_product(product["name"])
    quantity = in_freezer["quantity"] if in_freezer else 0
    return (
        f"📦 <b>{esc(product['name'])}</b>\n\n"
        f"Срок хранения после разморозки: {product['fridge_storage_time']} дн.\n"
        f"В морозильнике: {quantity} шт."
    )


def _validate_name(
        db: Database,
        name: str,
        ignore_id: int | None = None,
    ) -> str | None:
    """Возвращает текст ошибки или None, если название подходит.

    «Медовик» и «медовик» считаются одним товаром. ignore_id — товар,
    который переименовывают: ему можно поменять регистр букв.
    """
    if not name:
        return "Название не может быть пустым."
    if len(name) > MAX_NAME_LENGTH:
        return f"Слишком длинное название. Уложитесь в {MAX_NAME_LENGTH} символов."

    for product in db.search_products(name, limit=1_000):
        same_name = product["name"].casefold() == name.casefold()
        if same_name and product["id"] != ignore_id:
            return (
                f"Товар «{esc(product['name'])}» уже есть в справочнике. "
                "Введите другое название."
            )
    return None


def _parse_storage_days(text: str | None) -> int | None:
    days = parse_positive_int(text)
    if days is None or days > MAX_STORAGE_DAYS:
        return None
    return days


def _create_product(
        db: Database,
        name: str,
        days: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
    try:
        db.new_product(name, days)
    except ValueError as error:
        return f"⚠️ {esc(error)}", _back_to_products()

    return (
        f"✅ Товар <b>{esc(name)}</b> добавлен.\n"
        f"Срок хранения после разморозки: {days} дн.",
        ButtonBuilder.menu(
            [button("➕ Добавить ещё", "prod_add")],
            [button("⬅️ К товарам", "prod_page_1")],
        ),
    )


def _set_storage_days(
        db: Database,
        product: dict,
        days: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
    try:
        db.edit_product(product["name"], days)
    except ValueError as error:
        return f"⚠️ {esc(error)}", _back_to_products()

    product = db.get_product(product["name"])
    return (
        "✅ Срок хранения изменён. Он применяется к новым разморозкам, "
        "у уже размороженных партий срок не меняется.\n\n"
        f"{_product_card(db, product)}",
        ButtonBuilder.product_card(product["id"]),
    )


@router.callback_query(F.data.startswith("prod_page_"))
async def products_page_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_page_")
    page = ids[0] if ids else 1

    page_count, products = db.products_list(page=page, limit=PAGE_SIZE)
    if page_count is None:
        page = 1
        page_count, products = db.products_list(page=page, limit=PAGE_SIZE)

    add_row = [button("➕ Добавить товар", "prod_add")]
    back_row = [button("⬅️ Настройки", "settings")]
    if page_count == 0:
        await show(
            callback,
            "📦 <b>Справочник товаров пуст.</b>",
            ButtonBuilder.menu(add_row, back_row),
        )
        return

    await show(
        callback,
        f"📦 <b>Товары</b>    стр. {page}/{page_count}\n\n"
        "Выберите товар, чтобы изменить или удалить его.",
        ButtonBuilder.paginated(
            _product_items(products), "prod", page, page_count,
            extra_rows=[add_row, back_row],
        ),
    )


@router.callback_query(F.data == "prod_search")
async def products_search_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(ProductStates.search)
    await show(
        callback,
        "🔍 Введите часть названия товара:",
        ButtonBuilder.cancel(),
    )


@router.message(ProductStates.search, F.text)
async def products_search_message(
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
            _product_items(products[:SEARCH_LIMIT]), "prod"
        ),
    )


@router.callback_query(F.data.startswith("prod_view_"))
async def product_view_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_view_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return

    await show(
        callback,
        _product_card(db, product),
        ButtonBuilder.product_card(product["id"]),
    )


@router.callback_query(F.data == "prod_add")
async def product_add_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(ProductStates.name)
    await show(
        callback,
        "➕ <b>Новый товар</b>\n\nВведите название:",
        ButtonBuilder.cancel(),
    )


@router.message(ProductStates.name, F.text)
async def product_name_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    name = clean_name(message.text)
    error = _validate_name(db, name)
    if error is not None:
        await message.answer(error, reply_markup=ButtonBuilder.cancel())
        return

    await state.set_state(ProductStates.storage_time)
    await state.update_data(name=name)
    await message.answer(
        f"Сколько дней <b>{esc(name)}</b> хранится после разморозки?\n\n"
        "Выберите или введите число:",
        reply_markup=ButtonBuilder.storage_days("prod_newdays_"),
    )


@router.message(ProductStates.storage_time, F.text)
async def product_storage_time_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    days = _parse_storage_days(message.text)
    if days is None:
        await message.answer(
            STORAGE_DAYS_ERROR,
            reply_markup=ButtonBuilder.storage_days("prod_newdays_"),
        )
        return

    data = await state.get_data()
    await state.clear()
    text, keyboard = _create_product(db, data["name"], days)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(
    ProductStates.storage_time,
    F.data.startswith("prod_newdays_"),
    flags={"keep_state": True},
)
async def product_storage_time_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_newdays_")
    data = await state.get_data()
    await state.clear()
    if not ids or not 1 <= ids[0] <= MAX_STORAGE_DAYS:
        await show(callback, STORAGE_DAYS_ERROR, _back_to_products())
        return

    text, keyboard = _create_product(db, data["name"], ids[0])
    await show(callback, text, keyboard)


@router.callback_query(F.data.startswith("prod_days_"))
async def product_days_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_days_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return

    await state.set_state(ProductStates.edit_storage_time)
    await state.update_data(product_id=product["id"])
    await show(
        callback,
        f"<b>{esc(product['name'])}</b>\n"
        f"Сейчас срок хранения: {product['fridge_storage_time']} дн.\n\n"
        "Выберите новый срок или введите число дней:",
        ButtonBuilder.storage_days(
            f"prod_setdays_{product['id']}_",
            back_callback=f"prod_view_{product['id']}",
        ),
    )


@router.callback_query(F.data.startswith("prod_setdays_"))
async def product_setdays_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_setdays_")
    product = db.get_product_by_id(ids[0]) if ids and len(ids) == 2 else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return
    if not 1 <= ids[1] <= MAX_STORAGE_DAYS:
        await show(callback, STORAGE_DAYS_ERROR, _back_to_products())
        return

    text, keyboard = _set_storage_days(db, product, ids[1])
    await show(callback, text, keyboard)


@router.message(ProductStates.edit_storage_time, F.text)
async def product_days_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    data = await state.get_data()
    product = db.get_product_by_id(data.get("product_id", 0))
    if product is None:
        await state.clear()
        await message.answer(PRODUCT_GONE_TEXT, reply_markup=_back_to_products())
        return

    days = _parse_storage_days(message.text)
    if days is None:
        await message.answer(
            STORAGE_DAYS_ERROR,
            reply_markup=ButtonBuilder.cancel(back_callback=f"prod_view_{product['id']}"),
        )
        return

    await state.clear()
    text, keyboard = _set_storage_days(db, product, days)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("prod_rename_"))
async def product_rename_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_rename_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return

    await state.set_state(ProductStates.rename)
    await state.update_data(product_id=product["id"])
    await show(
        callback,
        f"Введите новое название для <b>{esc(product['name'])}</b>:",
        ButtonBuilder.cancel(back_callback=f"prod_view_{product['id']}"),
    )


@router.message(ProductStates.rename, F.text)
async def product_rename_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    data = await state.get_data()
    product = db.get_product_by_id(data.get("product_id", 0))
    if product is None:
        await state.clear()
        await message.answer(PRODUCT_GONE_TEXT, reply_markup=_back_to_products())
        return

    new_name = clean_name(message.text)
    back = ButtonBuilder.cancel(back_callback=f"prod_view_{product['id']}")
    if new_name == product["name"]:
        await message.answer("Название не изменилось. Введите другое:", reply_markup=back)
        return
    error = _validate_name(db, new_name, ignore_id=product["id"])
    if error is not None:
        await message.answer(error, reply_markup=back)
        return

    await state.clear()
    try:
        db.edit_product(
            product["name"], product["fridge_storage_time"], new_name=new_name
        )
    except ValueError as error:
        await message.answer(f"⚠️ {esc(error)}", reply_markup=_back_to_products())
        return

    renamed = db.get_product(new_name)
    await message.answer(
        f"✅ Товар переименован: {esc(product['name'])} → {esc(new_name)}\n\n"
        f"{_product_card(db, renamed)}",
        reply_markup=ButtonBuilder.product_card(renamed["id"]),
    )


@router.callback_query(F.data.startswith("prod_del_"))
async def product_delete_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_del_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return

    await show(
        callback,
        f"<b>Удалить товар {esc(product['name'])} из справочника?</b>\n\n"
        "История операций сохранится.",
        ButtonBuilder.confirm(
            f"prod_delyes_{product['id']}", f"prod_view_{product['id']}"
        ),
    )


@router.callback_query(F.data.startswith("prod_delyes_"))
async def product_delete_yes_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "prod_delyes_")
    product = db.get_product_by_id(ids[0]) if ids else None
    if product is None:
        await show(callback, PRODUCT_GONE_TEXT, _back_to_products())
        return

    try:
        db.delete_product(product["name"])
    except ValueError as error:
        await show(
            callback,
            f"⚠️ {esc(error)}",
            ButtonBuilder.menu([button("⬅️ К товару", f"prod_view_{product['id']}")]),
        )
        return

    await show(
        callback,
        f"🗑 Товар <b>{esc(product['name'])}</b> удалён из справочника.",
        _back_to_products(),
    )
