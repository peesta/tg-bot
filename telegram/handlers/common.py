import logging
import traceback
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiogram.utils.callback_answer import CallbackAnswer

from storage.db import Database
from telegram.keyboards import ButtonBuilder


# Подключается последним: сюда попадает всё, что не обработали разделы.
router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def unknown_message(
        message: Message,
        state: FSMContext,
        is_admin: bool,
    ) -> None:
    if await state.get_state() is not None:
        await message.answer(
            "Пришлите ответ текстом или нажмите «❌ Отмена».",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    await message.answer(
        "Воспользуйтесь кнопками меню:",
        reply_markup=ButtonBuilder.main_menu(is_admin),
    )


@router.callback_query(flags={"keep_state": True})
async def unknown_callback(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
    ) -> None:
    """Кнопка из старого сообщения или раздел, к которому больше нет доступа."""
    callback_answer.text = "Эта кнопка устарела. Откройте меню: /menu"
    callback_answer.show_alert = True


@router.errors()
async def errors_handler(event: ErrorEvent, db: Database, bot: Bot) -> bool:
    """Пишет ошибку в лог и таблицу errors, сообщает пользователю."""
    exception = event.exception
    logger.error("Ошибка при обработке обновления", exc_info=exception)

    try:
        db.log_error(
            type(exception).__name__,
            "".join(traceback.format_exception(exception)),
        )
    except Exception:
        logger.exception("Не удалось записать ошибку в базу данных")

    update = event.update
    chat_id = None
    if update.message is not None:
        chat_id = update.message.chat.id
    elif update.callback_query is not None:
        chat_id = update.callback_query.from_user.id

    if chat_id is not None:
        with suppress(TelegramAPIError):
            await bot.send_message(
                chat_id,
                "⚠️ Что-то пошло не так. Попробуйте ещё раз или откройте "
                "меню: /menu",
            )
    return True
