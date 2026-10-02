import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.utils import (
    DEFAULT_NOTIFY_TIME, NOTIFY_TIME_KEY, expiring_report, fit_message,
)


logger = logging.getLogger(__name__)

LAST_NOTIFICATION_KEY = "last_notification_date"
CHECK_INTERVAL_SECONDS = 30


async def send_daily_notification(
        bot: Bot,
        db: Database,
        admin_ids: frozenset[int],
        now: datetime | None = None,
    ) -> bool:
    """Раз в день после заданного времени рассылает список истекающих продуктов.

    Дата последней рассылки хранится в БД, поэтому после перезапуска бота
    уведомление за тот же день не повторяется. Возвращает True, если
    сообщения отправлялись.
    """
    now = now or datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    notify_time = db.get_setting(NOTIFY_TIME_KEY, DEFAULT_NOTIFY_TIME)

    if now.strftime("%H:%M") < notify_time:
        return False
    if db.get_setting(LAST_NOTIFICATION_KEY) == current_date:
        return False

    db.set_setting(LAST_NOTIFICATION_KEY, current_date)
    report = expiring_report(db.get_expiring_products())
    if report is None:
        return False
    report = fit_message(report)

    keyboard = ButtonBuilder.menu(
        [button("🗑 Перейти к списанию", "expiring")]
    )
    for user_id in sorted(set(db.active_users_ids()) | admin_ids):
        try:
            await bot.send_message(user_id, report, reply_markup=keyboard)
        except TelegramAPIError as error:
            logger.warning("Уведомление для %s не отправлено: %s", user_id, error)
        await asyncio.sleep(0.05)  # не упираться в лимиты Telegram
    return True


async def notification_loop(
        bot: Bot,
        db: Database,
        admin_ids: frozenset[int],
    ) -> None:
    """Фоновая задача: проверяет, не пора ли отправить уведомление."""
    while True:
        try:
            await send_daily_notification(bot, db, admin_ids)
        except Exception:
            logger.exception("Ошибка при отправке ежедневного уведомления")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
