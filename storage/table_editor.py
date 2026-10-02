"""Редактор таблиц базы для администратора.

Описание таблиц (русские названия, типы полей) нужно и сайту, и журналу
изменений: каждая правка записывается в change_log понятным текстом.
Правки идут мимо бизнес-проверок storage/db.py (например, переименование
товара здесь не переносит остатки), поэтому проверяются типы значений и
запрещено лишать прав самого себя.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from storage.db import Database
from storage.queries import normalize_text, page_of, search_cursor


OPERATION_TITLES = {
    "delivery": "Заморозка",
    "defrost": "Разморозка",
    "sale": "Продажа",
    "write_off": "Списание",
}
ROLE_TITLES = {"admin": "Администратор", "employee": "Сотрудник"}
MAX_TEXT_LENGTH = 200
MAX_LONG_TEXT_LENGTH = 20_000
MAX_NUMBER = 1_000_000_000


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    # text, longtext, int, date, datetime, bool, choice, product, user
    kind: str
    required: bool = False
    readonly: bool = False
    minimum: int | None = None
    choices: dict[str, str] | None = None


@dataclass(frozen=True)
class Table:
    name: str
    title: str
    description: str
    columns: tuple[Column, ...]
    # Как назвать строку в журнале изменений, поля — из строки таблицы.
    row_title: str
    note: str | None = None
    can_insert: bool = True
    newest_first: bool = False

    def column(self, name: str) -> Column:
        return next(column for column in self.columns if column.name == name)


ID_COLUMN = Column("id", "№", "int", readonly=True)
QUANTITY = Column("quantity", "Количество, шт.", "int", required=True, minimum=1)

TABLES: dict[str, Table] = {
    table.name: table for table in (
        Table(
            "products", "Товары",
            "Справочник: что продаётся и сколько хранится",
            (
                Column("name", "Название", "text", required=True),
                Column("fridge_storage_time", "Срок после разморозки, дней", "int",
                       required=True, minimum=1),
                Column("freezer_storage_time", "Срок в морозильнике, дней", "int",
                       minimum=1),
                Column("category", "Категория", "text"),
            ),
            row_title="«{name}»",
            note=(
                "Переименование здесь не меняет название у остатков в "
                "морозильнике и холодильнике — для этого есть раздел «Товары»."
            ),
        ),
        Table(
            "freezer", "Морозильник", "Сколько чего лежит в морозильнике",
            (Column("product_name", "Товар", "product", required=True), QUANTITY),
            row_title="«{product_name}»",
        ),
        Table(
            "fridge", "Холодильник", "Размороженные партии и их сроки",
            (
                Column("id", "№ партии", "int", readonly=True),
                Column("product_name", "Товар", "product", required=True),
                QUANTITY,
                Column("date_added", "Дата разморозки", "date", required=True),
                Column("expiration_date", "Годен до", "date", required=True),
            ),
            row_title="партия № {id} «{product_name}»",
        ),
        Table(
            "operations", "Журнал операций",
            "Заморозка, разморозка, продажи и списания",
            (
                ID_COLUMN,
                Column("operation_type", "Операция", "choice", required=True,
                       choices=OPERATION_TITLES),
                Column("product_name", "Товар", "text", required=True),
                Column("batch_id", "№ партии", "int", minimum=1),
                QUANTITY,
                Column("reason", "Причина", "text"),
                Column("created_at", "Дата и время", "datetime", required=True),
                Column("created_by", "Сотрудник", "user", required=True),
            ),
            row_title="запись № {id}",
            note="Это история работы. Правка записи не меняет остатки.",
            newest_first=True,
        ),
        Table(
            "users", "Сотрудники", "Имена, роли и доступ",
            (
                Column("telegram_id", "№", "int", readonly=True),
                Column("full_name", "Имя", "text", required=True),
                Column("role", "Роль", "choice", required=True, choices=ROLE_TITLES),
                Column("is_active", "Доступ", "bool"),
            ),
            row_title="«{full_name}» (№ {telegram_id})",
            note=(
                "Логин и пароль задаются в разделе «Сотрудники», там же "
                "добавляются новые сотрудники. Свою роль и доступ изменить нельзя."
            ),
            can_insert=False,
        ),
        Table(
            "errors", "Ошибки", "Ошибки, записанные сайтом",
            (
                ID_COLUMN,
                Column("error_type", "Тип ошибки", "text", required=True),
                Column("error_message", "Описание", "longtext", required=True),
                Column("created_at", "Когда", "datetime"),
            ),
            row_title="ошибка № {id}",
            newest_first=True,
        ),
    )
}


def table_spec(name: str) -> Table:
    """Описание таблицы; таблицы не из списка — KeyError."""
    return TABLES[name]


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def list_tables(db: Database) -> list[dict]:
    with db.cursor() as cursor:
        result = []
        for table in TABLES.values():
            cursor.execute(f"SELECT COUNT(*) FROM {quote(table.name)}")
            result.append({
                "name": table.name,
                "title": table.title,
                "description": table.description,
                "count": int(cursor.fetchone()[0]),
                "can_insert": table.can_insert,
            })
        return result


def options(db: Database, table: Table) -> dict[str, list[dict]]:
    """Варианты для выпадающих списков: товары, сотрудники, роли."""
    result = {}
    with db.cursor() as cursor:
        for column in table.columns:
            if column.kind == "choice":
                result[column.name] = [
                    {"value": value, "label": label}
                    for value, label in column.choices.items()
                ]
            elif column.kind == "product":
                cursor.execute("SELECT name FROM products ORDER BY name")
                result[column.name] = [
                    {"value": row["name"], "label": row["name"]}
                    for row in cursor.fetchall()
                ]
            elif column.kind == "user":
                cursor.execute(
                    "SELECT telegram_id, full_name FROM users ORDER BY full_name"
                )
                result[column.name] = [{"value": 0, "label": "Система"}] + [
                    {"value": row["telegram_id"], "label": row["full_name"]}
                    for row in cursor.fetchall()
                ]
    return result


def rows(
    db: Database,
    table: Table,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
    sort: str | None = None,
    descending: bool | None = None,
) -> tuple[int, list[dict]]:
    """Строки с поиском по всем полям; у каждой строки есть __rowid."""
    names = [column.name for column in table.columns]
    params: list = []
    where = f"FROM {quote(table.name)}"
    if query:
        where += " WHERE " + " OR ".join(
            f"instr(normalize({quote(name)}), ?) > 0" for name in names
        )
        params = [normalize_text(query)] * len(names)
    if descending is None:
        descending = table.newest_first and sort is None
    order = quote(sort) if sort in names else "rowid"
    order += " DESC" if descending else " ASC"

    with search_cursor(db) as cursor:
        return page_of(
            cursor,
            "SELECT rowid AS __rowid, " + ", ".join(map(quote, names)),
            where, params, order, page, limit,
        )


def get_row(db: Database, table: Table, rowid: int) -> dict | None:
    names = ", ".join(quote(column.name) for column in table.columns)
    with db.cursor() as cursor:
        cursor.execute(
            f"SELECT rowid AS __rowid, {names} FROM {quote(table.name)} "
            "WHERE rowid = ?",
            (rowid,),
        )
        row = cursor.fetchone()
        return None if row is None else dict(row)


# ---------- Проверка значений ----------

def _valid_date(text: str, formats: tuple[str, ...]) -> bool:
    for date_format in formats:
        try:
            datetime.strptime(text, date_format)
            return True
        except ValueError:
            continue
    return False


def _clean(db: Database, column: Column, value: object) -> object:
    """Приводит значение из формы к типу столбца или бросает ValueError."""
    label = f"«{column.label}»"
    if isinstance(value, str) and column.kind != "longtext":
        value = " ".join(value.split())
    if value is None or value == "":
        if column.required:
            raise ValueError(f"Заполните {label}")
        return None

    if column.kind in ("int", "user"):
        if isinstance(value, bool):
            raise ValueError(f"{label}: нужно целое число")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label}: нужно целое число") from None
        if column.minimum is not None and number < column.minimum:
            raise ValueError(f"{label}: число должно быть не меньше {column.minimum}")
        if abs(number) > MAX_NUMBER:
            raise ValueError(f"{label}: слишком большое число")
        if column.kind == "user" and number != 0:
            with db.cursor() as cursor:
                cursor.execute("SELECT 1 FROM users WHERE telegram_id = ?", (number,))
                if cursor.fetchone() is None:
                    raise ValueError(f"{label}: такого сотрудника нет")
        return number

    if column.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{label}: нужно «да» или «нет»")
        return int(value)

    if not isinstance(value, str):
        raise ValueError(f"{label}: нужен текст")
    if column.kind == "date" and not _valid_date(value, ("%Y-%m-%d",)):
        raise ValueError(f"{label}: выберите дату в календаре")
    if column.kind == "datetime" and not _valid_date(
        value, ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
    ):
        raise ValueError(f"{label}: выберите дату и время")
    if column.kind == "choice" and value not in column.choices:
        raise ValueError(f"{label}: выберите значение из списка")
    if column.kind == "product":
        with db.cursor() as cursor:
            cursor.execute("SELECT 1 FROM products WHERE name = ?", (value,))
            if cursor.fetchone() is None:
                raise ValueError(f"{label}: такого товара нет в справочнике")
    limit = MAX_LONG_TEXT_LENGTH if column.kind == "longtext" else MAX_TEXT_LENGTH
    if len(value) > limit:
        raise ValueError(f"{label}: слишком длинный текст (до {limit} символов)")
    return value


def clean_values(
    db: Database,
    table: Table,
    values: dict,
    current: dict | None = None,
) -> dict:
    """Проверяет значения новой (current=None) или изменяемой строки."""
    known = {column.name for column in table.columns}
    unknown = [name for name in values if name not in known]
    if unknown:
        raise ValueError(f"Нет таких полей: {', '.join(unknown)}")

    cleaned = {}
    for column in table.columns:
        if column.readonly:
            continue
        if column.name in values:
            cleaned[column.name] = _clean(db, column, values[column.name])
        elif current is None and column.required:
            raise ValueError(f"Заполните «{column.label}»")

    if table.name == "fridge":
        merged = {**(current or {}), **cleaned}
        if (
            merged.get("date_added") and merged.get("expiration_date")
            and merged["expiration_date"] < merged["date_added"]
        ):
            raise ValueError("«Годен до» не может быть раньше даты разморозки")
    return cleaned


def _display(column: Column, value: object) -> str:
    if value is None or value == "":
        return "пусто"
    if column.kind == "bool":
        return "да" if value else "нет"
    if column.kind == "choice":
        return column.choices.get(value, str(value))
    text = str(value)
    return text if len(text) <= 80 else text[:80] + "…"


def _row_title(table: Table, row: dict) -> str:
    try:
        return table.row_title.format(**row)
    except (KeyError, IndexError):
        return f"строка № {row.get('__rowid')}"


def _database_error(table: Table, error: sqlite3.Error) -> ValueError:
    """Понятный текст вместо сообщения SQLite."""
    message = str(error)
    for column in table.columns:
        if message.endswith(f"{table.name}.{column.name}"):
            if "UNIQUE" in message:
                return ValueError(f"Такое значение «{column.label}» уже есть в таблице")
            if "NOT NULL" in message:
                return ValueError(f"Заполните «{column.label}»")
    if "CHECK" in message:
        return ValueError("База не приняла значение: количество должно быть больше нуля")
    return ValueError(f"База не приняла изменения: {message}")


def _check_own_rights(table: Table, rowid: int, values: dict, acting_user: dict) -> None:
    """Администратор не может лишить себя прав ни здесь, ни в «Сотрудниках»."""
    if table.name != "users" or rowid != acting_user["id"]:
        return
    if "role" in values and values["role"] != acting_user["role"]:
        raise ValueError("Нельзя лишить себя прав: свою роль меняет другой администратор")
    if "is_active" in values and not values["is_active"]:
        raise ValueError("Нельзя отключить доступ самому себе")


# ---------- Изменение строк ----------

def insert_row(db: Database, table: Table, values: dict, acting_user: dict) -> int:
    if not table.can_insert:
        raise ValueError(f"В таблицу «{table.title}» строки добавляются в своём разделе")
    cleaned = clean_values(db, table, values)
    names = ", ".join(map(quote, cleaned))
    marks = ", ".join("?" for _ in cleaned)
    with db.cursor() as cursor:
        try:
            cursor.execute(
                f"INSERT INTO {quote(table.name)} ({names}) VALUES ({marks})",
                list(cleaned.values()),
            )
        except sqlite3.Error as error:
            raise _database_error(table, error) from None
        rowid = cursor.lastrowid
        row = {**cleaned, "__rowid": rowid, "id": rowid}
        db._log_change(
            cursor, "row_added",
            f"{table.title}: добавлена {_row_title(table, row)}: " + "; ".join(
                f"{table.column(name).label}: {_display(table.column(name), value)}"
                for name, value in cleaned.items()
            ),
            acting_user["id"], table.name,
        )
        return rowid


def update_row(
    db: Database, table: Table, rowid: int, values: dict, acting_user: dict
) -> dict:
    """Меняет поля строки и возвращает её новое состояние."""
    current = get_row(db, table, rowid)
    if current is None:
        raise ValueError("Строка не найдена: возможно, её уже удалили")
    cleaned = clean_values(db, table, values, current)
    _check_own_rights(table, rowid, cleaned, acting_user)
    changed = {name: value for name, value in cleaned.items() if current[name] != value}
    if not changed:
        return current

    assignments = ", ".join(f"{quote(name)} = ?" for name in changed)
    with db.cursor() as cursor:
        try:
            cursor.execute(
                f"UPDATE {quote(table.name)} SET {assignments} WHERE rowid = ?",
                [*changed.values(), rowid],
            )
        except sqlite3.Error as error:
            raise _database_error(table, error) from None
        db._log_change(
            cursor, "row_changed",
            f"{table.title}, {_row_title(table, current)}: " + "; ".join(
                f"{table.column(name).label}: "
                f"{_display(table.column(name), current[name])} → "
                f"{_display(table.column(name), value)}"
                for name, value in changed.items()
            ),
            acting_user["id"], table.name,
        )
    return get_row(db, table, rowid)


def delete_row(db: Database, table: Table, rowid: int, acting_user: dict) -> None:
    current = get_row(db, table, rowid)
    if current is None:
        raise ValueError("Строка не найдена: возможно, её уже удалили")
    if table.name == "users" and rowid == acting_user["id"]:
        raise ValueError("Нельзя удалить самого себя")

    with db.cursor() as cursor:
        cursor.execute(f"DELETE FROM {quote(table.name)} WHERE rowid = ?", (rowid,))
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
        )
        if table.name == "users" and cursor.fetchone() is not None:
            # Без сотрудника его логин бесполезен и только занимает имя.
            cursor.execute("DELETE FROM accounts WHERE user_id = ?", (rowid,))
        db._log_change(
            cursor, "row_deleted",
            f"{table.title}: удалена {_row_title(table, current)}: " + "; ".join(
                f"{column.label}: {_display(column, current[column.name])}"
                for column in table.columns
            ),
            acting_user["id"], table.name,
        )
