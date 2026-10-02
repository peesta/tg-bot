from contextlib import suppress
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.utils.callback_answer import CallbackAnswer, CallbackAnswerMiddleware

from storage.db import Database


Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessMiddleware(BaseMiddleware):
    """Пускает только активных пользователей из таблицы users и ADMIN_IDS.

    Пользователи сами не регистрируются: их добавляет администратор.
    Кладёт в данные обработчика флаг is_admin.
    """

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type != ChatType.PRIVATE:
            return None

        telegram_user = getattr(event, "from_user", None)
        if telegram_user is None:
            return None

        db: Database = data["db"]
        admin_ids: frozenset[int] = data.get("admin_ids", frozenset())

        is_owner = telegram_user.id in admin_ids
        user = db.get_user(telegram_user.id)
        if not is_owner and (user is None or not user["is_active"]):
            await self._deny(event, telegram_user.id)
            return None

        data["is_admin"] = is_owner or user["role"] == "admin"
        return await handler(event, data)

    @staticmethod
    async def _deny(event: TelegramObject, telegram_id: int) -> None:
        if isinstance(event, CallbackQuery):
            with suppress(TelegramBadRequest):
                await event.answer("⛔ У вас нет доступа к боту", show_alert=True)
            return

        await event.answer(
            "⛔ У вас нет доступа к боту.\n\n"
            f"Ваш Telegram ID: <code>{telegram_id}</code>\n"
            "Передайте его администратору, чтобы он добавил вас."
        )


class ResetStateMiddleware(BaseMiddleware):
    """Сбрасывает незаконченный ввод, когда пользователь нажимает кнопку.

    Иначе после ухода в другое меню следующий текст попал бы в старый
    сценарий (например, в ввод количества). Обработчики, которые продолжают
    сценарий, помечаются flags={"keep_state": True}.
    """

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state is not None and not get_flag(data, "keep_state"):
            await state.clear()
        return await handler(event, data)


class SafeCallbackAnswerMiddleware(CallbackAnswerMiddleware):
    """Автоматически отвечает на нажатие кнопки.

    Если нажатие обработано слишком поздно (например, бот был выключен),
    Telegram отклоняет ответ — это не ошибка обработчика.
    """

    async def answer(
        self,
        event: CallbackQuery,
        callback_answer: CallbackAnswer,
    ) -> None:
        with suppress(TelegramBadRequest):
            await super().answer(event, callback_answer)


class IsAdmin(Filter):
    """Пропускает только администраторов (флаг ставит AccessMiddleware)."""

    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return is_admin
