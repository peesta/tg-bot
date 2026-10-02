import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.utils import expiring_report, fit_message


logger = logging.getLogger(__name__)


async def send_expiring_notification(
        bot: Bot,
        db: Database,
        telegram_id: int,
    ) -> bool:
    """Присылает пользователю список продуктов с истекающим сроком.

    Возвращает True, если сообщение отправлено. Если таких продуктов нет,
    ничего не отправляет.
    """
    report = expiring_report(db.get_expiring_products())
    if report is None:
        return False

    keyboard = ButtonBuilder.menu(
        [button("🗑 Перейти к списанию", "expiring")]
    )
    try:
        await bot.send_message(
            telegram_id, fit_message(report), reply_markup=keyboard
        )
    except TelegramAPIError as error:
        logger.warning("Уведомление для %s не отправлено: %s", telegram_id, error)
        return False
    return True
