from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from storage.db import Database
from telegram.keyboards import ButtonBuilder
from telegram.middlewares import IsAdmin
from telegram.states import NotifyStates
from telegram.utils import (
    DEFAULT_NOTIFY_TIME, NOTIFY_TIME_KEY, parse_time, show,
)


# «⚙️ Настройки» и время ежедневного уведомления. Только администратор.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _notify_text(db: Database) -> str:
    notify_time = db.get_setting(NOTIFY_TIME_KEY, DEFAULT_NOTIFY_TIME)
    return (
        "⏰ <b>Время уведомления</b>\n\n"
        "Каждый день в это время бот присылает всем сотрудникам список "
        "продуктов, у которых заканчивается срок годности.\n\n"
        f"Сейчас: <b>{notify_time}</b>\n\n"
        "Выберите новое время или введите своё."
    )


@router.callback_query(F.data == "settings")
async def settings_callback(callback: CallbackQuery) -> None:
    await show(callback, "⚙️ <b>Настройки</b>", ButtonBuilder.settings())


@router.callback_query(F.data == "notify")
async def notify_callback(callback: CallbackQuery, db: Database) -> None:
    await show(callback, _notify_text(db), ButtonBuilder.notify())


@router.callback_query(F.data.startswith("notify_set_"))
async def notify_set_callback(callback: CallbackQuery, db: Database) -> None:
    raw_time = callback.data.removeprefix("notify_set_")
    notify_time = parse_time(f"{raw_time[:2]}:{raw_time[2:]}")
    if notify_time is not None:
        db.set_setting(NOTIFY_TIME_KEY, notify_time)
    await show(callback, _notify_text(db), ButtonBuilder.notify())


@router.callback_query(F.data == "notify_edit")
async def notify_edit_callback(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
    await state.set_state(NotifyStates.time)
    await show(
        callback,
        "Введите время в формате ЧЧ:ММ, например 08:30:",
        ButtonBuilder.cancel(back_callback="notify"),
    )


@router.message(NotifyStates.time, F.text)
async def notify_time_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    notify_time = parse_time(message.text)
    if notify_time is None:
        await message.answer(
            "Не понял время. Введите его в формате ЧЧ:ММ, например 08:30:",
            reply_markup=ButtonBuilder.cancel(back_callback="notify"),
        )
        return

    await state.clear()
    db.set_setting(NOTIFY_TIME_KEY, notify_time)
    await message.answer(_notify_text(db), reply_markup=ButtonBuilder.notify())
