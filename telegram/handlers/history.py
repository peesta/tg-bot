from aiogram import F, Router
from aiogram.types import CallbackQuery

from storage.db import SYSTEM_USER_ID, Database
from telegram.keyboards import ButtonBuilder
from telegram.utils import esc, format_datetime, parse_ids, show


router = Router()

HISTORY_PAGE_SIZE = 10


def _author(record: dict) -> str:
    if record["full_name"]:
        return record["full_name"]
    if record["created_by"] == SYSTEM_USER_ID:
        return "Система"
    return f"ID {record['created_by']}"


def _record_text(record: dict) -> str:
    return (
        f"<b>{format_datetime(record['created_at'])}</b> — "
        f"{esc(record['product_name'])} — {record['quantity']} шт.\n"
        f"Причина: {esc(record['reason'] or 'не указана')} · "
        f"{esc(_author(record))}"
    )


@router.callback_query(F.data.startswith("history_page_"))
async def history_callback(
        callback: CallbackQuery,
        db: Database,
    ) -> None:
    """Журнал списаний, новые записи первыми."""
    ids = parse_ids(callback.data, "history_page_")
    page = ids[0] if ids else 1

    page_count, records = db.write_off_history(page=page, limit=HISTORY_PAGE_SIZE)
    if page_count is None:
        page = 1
        page_count, records = db.write_off_history(page=page, limit=HISTORY_PAGE_SIZE)

    if page_count == 0:
        await show(callback, "📋 <b>Списаний пока не было.</b>", ButtonBuilder.menu())
        return

    text = "\n\n".join([
        f"📋 <b>История списаний</b>    стр. {page}/{page_count}",
        *map(_record_text, records),
    ])
    await show(callback, text, ButtonBuilder.pages("history", page, page_count))
