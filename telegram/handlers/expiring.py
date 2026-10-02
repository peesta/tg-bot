from aiogram import F, Router
from aiogram.types import CallbackQuery

from storage.db import Database
from telegram.keyboards import ButtonBuilder
from telegram.utils import esc, expiring_report, show


router = Router()

NOTHING_TEXT = (
    "✅ <b>Сегодня ни у одной партии не заканчивается срок, "
    "просроченных партий нет.</b>"
)


@router.callback_query(F.data == "expiring")
async def expiring_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Партии, у которых срок истекает сегодня, и просроченные."""
    result = db.get_expiring_products()
    report = expiring_report(result)
    if report is None:
        await show(callback, NOTHING_TEXT, ButtonBuilder.menu())
        return

    expired, expiring_today = result
    await show(
        callback,
        report,
        ButtonBuilder.expiring(len(expired) + len(expiring_today)),
    )


@router.callback_query(F.data == "expiring_clear")
async def expiring_clear_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Подтверждение списания всех просроченных и истекающих сегодня партий."""
    result = db.get_expiring_products()
    if result is None:
        await show(callback, NOTHING_TEXT, ButtonBuilder.menu())
        return

    batches = result[0] + result[1]
    total = sum(batch["quantity"] for batch in batches)
    await show(
        callback,
        "<b>Списать все просроченные партии и партии, у которых срок "
        "заканчивается сегодня?</b>\n\n"
        f"Партий: {len(batches)}, всего {total} шт.\n"
        "Причина: Просрочено",
        ButtonBuilder.confirm("expiring_clear_yes", "expiring"),
    )


@router.callback_query(F.data == "expiring_clear_yes")
async def expiring_clear_yes_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    result = db.clear_expired_product(user_id=callback.from_user.id)
    if result is False:
        await show(callback, NOTHING_TEXT, ButtonBuilder.menu())
        return

    await show(callback, f"✅ {esc(result)}", ButtonBuilder.menu())
