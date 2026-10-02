"""Общие помощники сайта: доступ к базе, форматирование, страницы."""
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from flask import current_app, g, request

from storage.db import Database, normalize_text


PAGE_SIZE = 20
MAX_QUANTITY = 100_000
MAX_STORAGE_DAYS = 365
MAX_NAME_LENGTH = 60
MAX_REASON_LENGTH = 200

WRITE_OFF_REASONS = {
    "expired": "Просрочено",
    "damaged": "Повреждено",
    "staff": "Для сотрудника",
}

ROLE_TITLES = {
    "admin": "Администратор",
    "employee": "Сотрудник",
}

OPERATION_TITLES = {
    "delivery": "Заморозка",
    "defrost": "Разморозка",
    "sale": "Продажа",
    "write_off": "Списание",
}

ACTION_TITLES = {
    "login": "Вход",
    "login_failed": "Неудачный вход",
    "logout": "Выход",
    "password_changed": "Смена своего пароля",
    "user_created": "Добавлен сотрудник",
    "user_updated": "Изменён сотрудник",
    "product_created": "Добавлен товар",
    "product_updated": "Изменён товар",
    "product_deleted": "Удалён товар",
    "db_insert": "БД: добавлена строка",
    "db_update": "БД: изменена строка",
    "db_delete": "БД: удалена строка",
    "google_export": "Экспорт в Google Таблицу",
    "google_import": "Импорт из Google Таблицы",
    "backup_created": "Создана копия базы",
    "backup_restored": "База восстановлена из копии",
    "backup_deleted": "Удалена копия базы",
}


def get_db() -> Database:
    return current_app.extensions["db"]


def client_ip() -> str | None:
    return request.remote_addr


def audit(action: str, details: str | None = None) -> None:
    """Записывает действие текущего пользователя в журнал действий."""
    user = g.get("user")
    get_db().log_action(
        action,
        details=details,
        user_id=user["id"] if user else None,
        username=user["username"] if user else None,
        ip=client_ip(),
    )


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def format_date(iso_date: str | None, with_year: bool = True) -> str:
    """2026-08-03 -> 03.08.2026 (или 03.08 без года)."""
    if not iso_date:
        return ""
    try:
        date = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    return date.strftime("%d.%m.%Y" if with_year else "%d.%m")


def format_datetime(iso_datetime: str | None) -> str:
    """2026-08-03 14:30[:15] -> 03.08.2026 14:30"""
    if not iso_datetime:
        return ""
    for source_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            moment = datetime.strptime(iso_datetime, source_format)
        except ValueError:
            continue
        return moment.strftime("%d.%m.%Y %H:%M")
    return iso_datetime


def batch_status(expiration_date: str) -> str:
    """expired — просрочено, today — срок истекает сегодня, fresh — годно."""
    current_date = today()
    if expiration_date < current_date:
        return "expired"
    if expiration_date == current_date:
        return "today"
    return "fresh"


def matches(text: str | None, query: str) -> bool:
    """Поиск без учёта регистра и разницы между «е» и «ё»."""
    return normalize_text(query) in (normalize_text(text) or "")


def parse_positive_int(text: str | None, maximum: int | None = None) -> int | None:
    """Целое число больше нуля (и не больше maximum) или None."""
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    if value <= 0 or (maximum is not None and value > maximum):
        return None
    return value


def parse_date(text: str | None) -> str | None:
    """Дата из поля <input type="date"> (ГГГГ-ММ-ДД) или None."""
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def clean_name(text: str | None) -> str:
    """Убирает лишние пробелы из названия или имени."""
    return " ".join((text or "").split())


def page_arg() -> int:
    return parse_positive_int(request.args.get("page")) or 1


@dataclass
class Page:
    """Страница списка для шаблона macros.pagination."""

    items: list
    page: int
    pages: int
    total: int

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def make_page(total: int, items: list, page: int, per_page: int) -> Page:
    return Page(items, page, max(ceil(total / per_page), 1), total)


def paginate(items: list, page: int, per_page: int = PAGE_SIZE) -> Page:
    """Разбивает готовый список на страницы; лишний номер — последняя."""
    pages = max(ceil(len(items) / per_page), 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return Page(items[start:start + per_page], page, pages, len(items))


def sum_by_product(batches: list[dict]) -> list[tuple[str, int]]:
    """[(товар, всего штук)] по партиям, в порядке первого появления."""
    totals: dict[str, int] = {}
    for batch in batches:
        name = batch["product_name"]
        totals[name] = totals.get(name, 0) + batch["quantity"]
    return list(totals.items())
