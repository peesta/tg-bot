from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.callback_answer import CallbackAnswer

from storage.db import Database
from telegram.keyboards import WRITE_OFF_REASONS, ButtonBuilder, button
from telegram.states import WriteOffStates
from telegram.utils import (
    PAGE_SIZE, SEARCH_LIMIT, batch_mark, batch_title, esc, parse_ids,
    parse_positive_int, show,
)


# «🗑️ Списание и продажа»: работа с отдельной партией холодильника.
router = Router()

BATCH_GONE_TEXT = "Этой партии уже нет: её списали или продали полностью."
MAX_REASON_LENGTH = 200


def _batch_items(batches: list[dict]) -> list[tuple[str, str]]:
    return [
        (
            f"{batch_mark(batch['expiration_date'])}{batch_title(batch)}",
            f"batch_select_{batch['id']}",
        )
        for batch in batches
    ]


def _after_operation_keyboard() -> InlineKeyboardMarkup:
    return ButtonBuilder.menu(
        [button("🗑️ Списание и продажа", "batch_page_1")]
    )


async def _ask_quantity(
        state: FSMContext,
        batch: dict,
        operation_type: str,
        reason: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
    """Запоминает операцию и возвращает вопрос о количестве."""
    await state.set_state(WriteOffStates.quantity)
    await state.update_data(
        batch_id=batch["id"],
        operation_type=operation_type,
        reason=reason,
    )

    if operation_type == "sale":
        question = "<b>Сколько продано?</b>"
    else:
        question = f"<b>Сколько списать?</b>\nПричина: {esc(reason)}"

    text = (
        f"{esc(batch_title(batch))}\n\n"
        f"{question}\n\n"
        f"Введите количество (в партии {batch['quantity']} шт.):"
    )
    return text, ButtonBuilder.whole_batch(batch["id"], batch["quantity"])


def _complete(
        db: Database,
        data: dict,
        quantity: int,
        user_id: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
    """Списывает или продаёт товар из партии."""
    result = db.clear_expired_product(
        id=data["batch_id"],
        quantity=quantity,
        operation_type=data["operation_type"],
        user_id=user_id,
        reason=data.get("reason"),
    )
    if result is False:
        return (
            "⚠️ Не получилось: партия уже закрыта или в ней меньше товара.",
            _after_operation_keyboard(),
        )
    return f"✅ {esc(result)}", _after_operation_keyboard()


@router.callback_query(F.data.startswith("batch_page_"))
async def batch_page_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Партии холодильника по 5 на странице."""
    batches = db.fridge_batches_list()
    if not batches:
        await show(callback, "<b>В холодильнике нет партий.</b>", ButtonBuilder.menu())
        return

    page_count = (len(batches) + PAGE_SIZE - 1) // PAGE_SIZE
    ids = parse_ids(callback.data, "batch_page_")
    page = min(max(ids[0] if ids else 1, 1), page_count)
    page_batches = batches[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]

    text = f"<b>Выберите продукт:</b>    стр. {page}/{page_count}"
    if any(batch_mark(batch["expiration_date"]) for batch in page_batches):
        text += "\n\n⚠️ — срок истекает сегодня, ❌ — просрочено"

    await show(
        callback,
        text,
        ButtonBuilder.paginated(
            _batch_items(page_batches), "batch", page, page_count
        ),
    )


@router.callback_query(F.data == "batch_search")
async def batch_search_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(WriteOffStates.search)
    await show(
        callback,
        "🔍 Введите часть названия продукта:",
        ButtonBuilder.cancel(),
    )


@router.message(WriteOffStates.search, F.text)
async def batch_search_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    query = message.text.strip()
    batches = db.search_fridge_batches(query, limit=SEARCH_LIMIT + 1)
    await state.clear()

    if not batches:
        text = f"По запросу «{esc(query)}» партий не найдено."
    elif len(batches) > SEARCH_LIMIT:
        text = (
            f"<b>Найдено по запросу «{esc(query)}»:</b>\n"
            f"Показаны первые {SEARCH_LIMIT}, уточните запрос."
        )
    else:
        text = f"<b>Найдено по запросу «{esc(query)}»:</b>"

    await message.answer(
        text,
        reply_markup=ButtonBuilder.search_results(
            _batch_items(batches[:SEARCH_LIMIT]), "batch"
        ),
    )


@router.callback_query(F.data.startswith("batch_select_"))
async def batch_select_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "batch_select_")
    batch = db.get_fridge_batch(ids[0]) if ids else None
    if batch is None:
        await show(callback, BATCH_GONE_TEXT, ButtonBuilder.back_to_list("batch"))
        return

    await show(
        callback,
        f"<b>Выбран:</b>\n{batch_mark(batch['expiration_date'])}"
        f"{esc(batch_title(batch))}",
        ButtonBuilder.batch_actions(batch["id"]),
    )


@router.callback_query(F.data.startswith("batch_writeoff_"))
async def batch_writeoff_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "batch_writeoff_")
    batch = db.get_fridge_batch(ids[0]) if ids else None
    if batch is None:
        await show(callback, BATCH_GONE_TEXT, ButtonBuilder.back_to_list("batch"))
        return

    await show(
        callback,
        f"{esc(batch_title(batch))}\n\n<b>Причина списания?</b>",
        ButtonBuilder.write_off_reasons(batch["id"]),
    )


@router.callback_query(F.data.startswith("batch_reason_"))
async def batch_reason_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    batch_id, _, code = callback.data.removeprefix("batch_reason_").partition("_")
    batch = db.get_fridge_batch(int(batch_id)) if batch_id.isdigit() else None
    if batch is None:
        await show(callback, BATCH_GONE_TEXT, ButtonBuilder.back_to_list("batch"))
        return

    if code == "other":
        await state.set_state(WriteOffStates.reason)
        await state.update_data(batch_id=batch["id"])
        await show(
            callback,
            f"{esc(batch_title(batch))}\n\n✏️ <b>Напишите причину списания:</b>",
            ButtonBuilder.cancel(),
        )
        return

    reason = WRITE_OFF_REASONS.get(code)
    if reason is None:
        await show(
            callback,
            f"{esc(batch_title(batch))}\n\n<b>Причина списания?</b>",
            ButtonBuilder.write_off_reasons(batch["id"]),
        )
        return

    text, keyboard = await _ask_quantity(state, batch, "write_off", reason)
    await show(callback, text, keyboard)


@router.message(WriteOffStates.reason, F.text)
async def batch_reason_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    """Причина списания, введённая вручную."""
    reason = " ".join(message.text.split())
    if len(reason) > MAX_REASON_LENGTH:
        await message.answer(
            f"Слишком длинная причина. Уложитесь в {MAX_REASON_LENGTH} символов.",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    data = await state.get_data()
    batch = db.get_fridge_batch(data.get("batch_id", 0))
    if batch is None:
        await state.clear()
        await message.answer(
            BATCH_GONE_TEXT, reply_markup=ButtonBuilder.back_to_list("batch")
        )
        return

    text, keyboard = await _ask_quantity(state, batch, "write_off", reason)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("batch_sale_"))
async def batch_sale_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
    ) -> None:
    ids = parse_ids(callback.data, "batch_sale_")
    batch = db.get_fridge_batch(ids[0]) if ids else None
    if batch is None:
        await show(callback, BATCH_GONE_TEXT, ButtonBuilder.back_to_list("batch"))
        return

    text, keyboard = await _ask_quantity(state, batch, "sale")
    await show(callback, text, keyboard)


@router.message(WriteOffStates.quantity, F.text)
async def batch_quantity_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    data = await state.get_data()
    batch = db.get_fridge_batch(data.get("batch_id", 0))
    if batch is None:
        await state.clear()
        await message.answer(
            BATCH_GONE_TEXT, reply_markup=ButtonBuilder.back_to_list("batch")
        )
        return

    quantity = parse_positive_int(message.text)
    if quantity is None:
        await message.answer(
            "Введите целое число больше нуля.",
            reply_markup=ButtonBuilder.whole_batch(batch["id"], batch["quantity"]),
        )
        return
    if quantity > batch["quantity"]:
        await message.answer(
            f"В партии только {batch['quantity']} шт. "
            "Введите число не больше остатка.",
            reply_markup=ButtonBuilder.whole_batch(batch["id"], batch["quantity"]),
        )
        return

    await state.clear()
    text, keyboard = _complete(db, data, quantity, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(
    WriteOffStates.quantity,
    F.data.startswith("batch_all_"),
    flags={"keep_state": True},
)
async def batch_all_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
        callback_answer: CallbackAnswer,
    ) -> None:
    """Кнопка «Вся партия» на шаге ввода количества."""
    data = await state.get_data()
    ids = parse_ids(callback.data, "batch_all_")
    if not ids or ids[0] != data.get("batch_id"):
        # Кнопка из старого сообщения, а ввод уже идёт для другой партии.
        callback_answer.text = "Эта кнопка устарела"
        callback_answer.show_alert = True
        return

    await state.clear()
    batch = db.get_fridge_batch(ids[0])
    if batch is None:
        await show(callback, BATCH_GONE_TEXT, ButtonBuilder.back_to_list("batch"))
        return

    text, keyboard = _complete(db, data, batch["quantity"], callback.from_user.id)
    await show(callback, text, keyboard)
