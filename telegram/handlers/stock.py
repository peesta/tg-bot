from aiogram import F, Router
from aiogram.types import CallbackQuery

from storage.db import Database
from telegram.keyboards import ButtonBuilder, button
from telegram.utils import esc, format_date, show, today


router = Router()


def _batch_line(batch: dict) -> str:
    return (
        f"{esc(batch['product_name'])} — {batch['quantity']} шт — "
        f"до {format_date(batch['expiration_date'], with_year=False)}"
    )


@router.callback_query(F.data == "stock")
async def stock_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Все партии холодильника; просроченные — отдельно."""
    keyboard = ButtonBuilder.menu([button("🔄 Обновить", "stock")])
    batches = db.fridge_batches_list()
    if not batches:
        await show(callback, "📊 <b>В холодильнике нет партий.</b>", keyboard)
        return

    current_date = today()
    expired = [b for b in batches if b["expiration_date"] < current_date]
    expiring_today = [b for b in batches if b["expiration_date"] == current_date]
    fresh = [b for b in batches if b["expiration_date"] > current_date]

    blocks = ["📊 <b>Остатки в холодильнике</b>"]
    if fresh:
        blocks.append(
            "\n".join(["✅ <b>Годные:</b>", *map(_batch_line, fresh)])
        )
    if expiring_today:
        blocks.append(
            "\n".join(["⚠️ <b>Срок истекает сегодня:</b>", *map(_batch_line, expiring_today)])
        )
    if expired:
        blocks.append(
            "\n".join(["❌ <b>Просрочено:</b>", *map(_batch_line, expired)])
        )

    await show(callback, "\n\n".join(blocks), keyboard)
