import html
import re
from datetime import datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


PAGE_SIZE = 5
SEARCH_LIMIT = 10
MAX_QUANTITY = 100_000
MAX_STORAGE_DAYS = 365
MAX_NAME_LENGTH = 60
MAX_MESSAGE_LENGTH = 4096

NOTIFY_TIME_KEY = "notify_time"
DEFAULT_NOTIFY_TIME = "09:00"


def esc(value: object) -> str:
    """Экранирует текст для HTML-разметки сообщений."""
    return html.escape(str(value), quote=False)


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def format_date(iso_date: str, with_year: bool = True) -> str:
    """2026-08-03 -> 03.08.2026 (или 03.08 без года)."""
    try:
        date = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    return date.strftime("%d.%m.%Y" if with_year else "%d.%m")


def format_datetime(iso_datetime: str) -> str:
    """2026-08-03 14:30 -> 03.08.2026 14:30"""
    try:
        moment = datetime.strptime(iso_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        return iso_datetime
    return moment.strftime("%d.%m.%Y %H:%M")


def parse_ids(data: str | None, prefix: str) -> list[int] | None:
    """Достаёт числа из callback_data вида «prefix_12_3» -> [12, 3]."""
    if not data or not data.startswith(prefix):
        return None
    try:
        return [int(part) for part in data.removeprefix(prefix).split("_")]
    except ValueError:
        return None


def parse_positive_int(text: str | None) -> int | None:
    """Возвращает целое число больше нуля или None."""
    if text is None:
        return None
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def parse_time(text: str | None) -> str | None:
    """Принимает «9», «9:30», «09:30», «9.30» и возвращает «09:30»."""
    if text is None:
        return None
    match = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", text.strip())
    if match is None:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2) or 0)
    if hours > 23 or minutes > 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def clean_name(text: str | None) -> str:
    """Убирает лишние пробелы из названия или имени."""
    return " ".join((text or "").split())


def fit_message(text: str) -> str:
    """Обрезает слишком длинный текст по границе строки."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        return text
    cut = text[:MAX_MESSAGE_LENGTH - 50]
    cut = cut[:cut.rfind("\n")] if "\n" in cut else cut
    return f"{cut}\n\n… список не поместился в сообщение целиком"


async def show(
        callback: CallbackQuery,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
    """Показывает новый экран вместо сообщения с нажатой кнопкой."""
    text = fit_message(text)
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return
    # Сообщение слишком старое или недоступно — отправляем новое.
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=reply_markup
    )


def batch_mark(expiration_date: str) -> str:
    """❌ — просрочено, ⚠️ — срок истекает сегодня."""
    current_date = today()
    if expiration_date < current_date:
        return "❌ "
    if expiration_date == current_date:
        return "⚠️ "
    return ""


def batch_title(batch: dict) -> str:
    """Медовик — 3 шт. до 03.08.2026 (без HTML, подходит для кнопок)."""
    return (
        f"{batch['product_name']} — {batch['quantity']} шт. "
        f"до {format_date(batch['expiration_date'])}"
    )


def _sum_by_product(batches: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for batch in batches:
        name = batch["product_name"]
        totals[name] = totals.get(name, 0) + batch["quantity"]
    return totals


def expiring_report(
        result: tuple[list[dict], list[dict]] | None,
    ) -> str | None:
    """Текст про партии, у которых срок истекает сегодня или уже истёк.

    Принимает результат Database.get_expiring_products().
    """
    if not result:
        return None

    expired, expiring_today = result
    blocks = []
    if expiring_today:
        lines = ["⚠️ <b>Сегодня заканчивается срок годности:</b>", ""]
        lines += [
            f"{esc(name)} — {quantity} шт"
            for name, quantity in _sum_by_product(expiring_today).items()
        ]
        blocks.append("\n".join(lines))
    if expired:
        lines = ["❌ <b>Срок годности уже истёк:</b>", ""]
        lines += [
            f"{esc(name)} — {quantity} шт"
            for name, quantity in _sum_by_product(expired).items()
        ]
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) or None
