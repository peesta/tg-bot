import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from storage.db import Database
from storage.google_sheets import (
    GoogleSheetsError, ImportDataError, export_to_google, import_from_google,
    spreadsheet_url,
)
from telegram.keyboards import ButtonBuilder, button
from telegram.middlewares import IsAdmin
from telegram.utils import esc, show


# «⚙️ Настройки» → экспорт и импорт Google Таблицы. Только администратор.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

# Экспорт и импорт не должны идти одновременно.
sync_lock = asyncio.Lock()

MAX_SHOWN_ERRORS = 15
SHEET_TITLES = {
    "products": "товары",
    "freezer": "морозильник",
    "fridge": "партии холодильника",
}


def _back_to_settings() -> InlineKeyboardMarkup:
    return ButtonBuilder.menu([button("⬅️ Настройки", "settings")])


def _result_keyboard(google_table: str) -> InlineKeyboardMarkup:
    return ButtonBuilder.menu(
        [InlineKeyboardButton(
            text="🔗 Открыть таблицу", url=spreadsheet_url(google_table)
        )],
        [button("⬅️ Настройки", "settings")],
    )


def _counts_text(counts: dict[str, int]) -> str:
    return "\n".join(
        f"{title} ({SHEET_TITLES[title]}): {count}"
        for title, count in counts.items()
    )


def _errors_text(errors: list[str]) -> str:
    lines = [f"• {esc(error)}" for error in errors[:MAX_SHOWN_ERRORS]]
    if len(errors) > MAX_SHOWN_ERRORS:
        lines.append(f"… и ещё {len(errors) - MAX_SHOWN_ERRORS}")
    return "\n".join(lines)


@router.callback_query(F.data == "gsheet_export")
async def export_callback(callback: CallbackQuery) -> None:
    await show(
        callback,
        "📤 <b>Экспорт в Google Таблицу</b>\n\n"
        "Листы fridge, freezer и products будут полностью очищены и "
        "заполнены текущими данными из базы.\n\nПродолжить?",
        ButtonBuilder.confirm("gsheet_export_yes", "settings"),
    )


@router.callback_query(
    F.data == "gsheet_export_yes",
    flags={"callback_answer": {"pre": True}},  # ответ на кнопку сразу, выгрузка долгая
)
async def export_yes_callback(
        callback: CallbackQuery,
        db: Database,
        google_table: str | None = None,
    ) -> None:
    if sync_lock.locked():
        await show(
            callback,
            "⏳ Уже идёт экспорт или импорт. Подождите и попробуйте снова.",
            _back_to_settings(),
        )
        return

    async with sync_lock:
        await show(callback, "⏳ Выгружаю данные в Google Таблицу…")
        try:
            counts = await asyncio.to_thread(export_to_google, db, google_table)
        except GoogleSheetsError as error:
            await show(
                callback,
                f"⚠️ <b>Экспорт не выполнен.</b>\n\n{esc(error)}",
                _back_to_settings(),
            )
            return

    await show(
        callback,
        "✅ <b>Экспорт завершён.</b> Выгружено строк:\n\n"
        f"{_counts_text(counts)}",
        _result_keyboard(google_table),
    )


@router.callback_query(F.data == "gsheet_import")
async def import_callback(callback: CallbackQuery) -> None:
    await show(
        callback,
        "📥 <b>Импорт из Google Таблицы</b>\n\n"
        "Товары, морозильник и холодильник в базе будут <b>заменены</b> "
        "данными с листов products, freezer и fridge. Сотрудники и журнал "
        "операций не изменятся.\n\n"
        "Сначала бот проверит все строки: если найдёт ошибки, база "
        "останется как есть. Перед заменой сохранится копия базы.\n\n"
        "Продолжить?",
        ButtonBuilder.confirm("gsheet_import_yes", "settings"),
    )


@router.callback_query(
    F.data == "gsheet_import_yes",
    flags={"callback_answer": {"pre": True}},
)
async def import_yes_callback(
        callback: CallbackQuery,
        db: Database,
        google_table: str | None = None,
    ) -> None:
    if sync_lock.locked():
        await show(
            callback,
            "⏳ Уже идёт экспорт или импорт. Подождите и попробуйте снова.",
            _back_to_settings(),
        )
        return

    async with sync_lock:
        await show(callback, "⏳ Загружаю данные из Google Таблицы…")
        try:
            counts, backup_path = await asyncio.to_thread(
                import_from_google, db, google_table
            )
        except ImportDataError as error:
            await show(
                callback,
                "⚠️ <b>Импорт не выполнен, база не изменена.</b>\n\n"
                f"Исправьте в таблице:\n{_errors_text(error.errors)}",
                _back_to_settings(),
            )
            return
        except GoogleSheetsError as error:
            await show(
                callback,
                f"⚠️ <b>Импорт не выполнен, база не изменена.</b>\n\n{esc(error)}",
                _back_to_settings(),
            )
            return

    await show(
        callback,
        "✅ <b>Импорт завершён.</b> Загружено строк:\n\n"
        f"{_counts_text(counts)}\n\n"
        f"Копия базы до импорта: <code>{esc(backup_path)}</code>",
        _result_keyboard(google_table),
    )
