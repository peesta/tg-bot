"""Запросы на чтение для сайта: списки, сводка, журналы с фильтрами.

Методы изменения данных остаются в storage/db.py. Даты возвращаются как
в базе (ГГГГ-ММ-ДД): в формат ДД.ММ.ГГГГ их переводит браузер.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from storage.db import Database


def normalize_text(text: object) -> str | None:
    """Текст для поиска без учёта регистра и разницы между «е» и «ё».

    Встроенные LOWER и LIKE в SQLite не понимают регистр кириллицы,
    поэтому функция подключается к запросам как normalize().
    """
    if text is None:
        return None
    return str(text).casefold().replace("ё", "е")


@contextmanager
def search_cursor(db: Database) -> Iterator[sqlite3.Cursor]:
    """Курсор базы с функцией normalize() для поиска."""
    connection = db.get_conn()
    connection.create_function("normalize", 1, normalize_text, deterministic=True)
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def page_of(
    cursor: sqlite3.Cursor,
    select: str,
    where: str,
    params: list,
    order: str,
    page: int,
    limit: int,
) -> tuple[int, list[dict]]:
    """Всего строк и строки страницы page (страницы с единицы)."""
    cursor.execute(f"SELECT COUNT(*) {where}", params)
    total = int(cursor.fetchone()[0])
    cursor.execute(
        f"{select} {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, limit, (max(page, 1) - 1) * limit],
    )
    return total, [dict(row) for row in cursor.fetchall()]


def catalog(db: Database) -> list[dict]:
    """Справочник товаров с остатками в морозильнике и холодильнике,
    по названию."""
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT products.rowid AS id, products.name,
                products.fridge_storage_time, products.freezer_storage_time,
                products.category,
                COALESCE(freezer.quantity, 0) AS freezer_quantity,
                (
                    SELECT COALESCE(SUM(fridge.quantity), 0) FROM fridge
                    WHERE fridge.product_name = products.name
                ) AS fridge_quantity
            FROM products
            LEFT JOIN freezer ON freezer.product_name = products.name
            ORDER BY products.name ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def freezer_items(db: Database) -> list[dict]:
    """Остатки морозильника со сроком хранения после разморозки."""
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT freezer.rowid AS id, freezer.product_name, freezer.quantity,
                products.fridge_storage_time
            FROM freezer
            LEFT JOIN products ON products.name = freezer.product_name
            ORDER BY freezer.product_name ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def operations_log(
    db: Database,
    page: int = 1,
    limit: int = 50,
    operation_type: str | None = None,
    user_id: int | None = None,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[int, list[dict]]:
    """Журнал операций с фильтрами, новые первыми: (всего, строки).

    date_from и date_to — даты ГГГГ-ММ-ДД включительно.
    """
    conditions, params = [], []
    if operation_type:
        conditions.append("operations.operation_type = ?")
        params.append(operation_type)
    if user_id is not None:
        conditions.append("operations.created_by = ?")
        params.append(user_id)
    if query:
        conditions.append(
            "(instr(normalize(operations.product_name), ?) > 0 "
            "OR instr(normalize(operations.reason), ?) > 0)"
        )
        params += [normalize_text(query)] * 2
    if date_from:
        conditions.append("operations.created_at >= ?")
        params.append(date_from)
    if date_to:
        # «2026-10-02 23:59» < «2026-10-02~»: тильда больше цифр и пробела.
        conditions.append("operations.created_at < ?")
        params.append(f"{date_to}~")
    where = "FROM operations LEFT JOIN users ON users.telegram_id = operations.created_by"
    if conditions:
        where += " WHERE " + " AND ".join(conditions)

    with search_cursor(db) as cursor:
        return page_of(
            cursor,
            "SELECT operations.id, operations.operation_type, "
            "operations.product_name, operations.batch_id, operations.quantity, "
            "operations.reason, operations.created_at, operations.created_by, "
            "users.full_name",
            where, params, "operations.id DESC", page, limit,
        )


def change_log(
    db: Database,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
) -> tuple[int, list[dict]]:
    """Журнал изменений (сотрудники, товары, таблицы), новые первыми."""
    params: list = []
    where = "FROM change_log LEFT JOIN users ON users.telegram_id = change_log.user_id"
    if query:
        where += (
            " WHERE instr(normalize(change_log.details), ?) > 0"
            " OR instr(normalize(users.full_name), ?) > 0"
        )
        params = [normalize_text(query)] * 2
    with search_cursor(db) as cursor:
        return page_of(
            cursor,
            "SELECT change_log.id, change_log.created_at, change_log.user_id, "
            "change_log.action, change_log.table_name, change_log.details, "
            "users.full_name",
            where, params, "change_log.id DESC", page, limit,
        )


def errors_list(db: Database, page: int = 1, limit: int = 50) -> tuple[int, list[dict]]:
    """Ошибки, новые первыми: (всего, строки)."""
    with db.cursor() as cursor:
        return page_of(
            cursor,
            "SELECT id, error_type, error_message, created_at",
            "FROM errors", [], "id DESC", page, limit,
        )


def stats(db: Database) -> dict[str, int]:
    """Сводка для главной страницы администратора."""
    current_date = today()
    queries = {
        "products": ("SELECT COUNT(*) FROM products", ()),
        "freezer_items": ("SELECT COUNT(*) FROM freezer", ()),
        "freezer_quantity": ("SELECT COALESCE(SUM(quantity), 0) FROM freezer", ()),
        "fridge_batches": ("SELECT COUNT(*) FROM fridge", ()),
        "fridge_quantity": ("SELECT COALESCE(SUM(quantity), 0) FROM fridge", ()),
        "expiring_today": (
            "SELECT COUNT(*) FROM fridge WHERE expiration_date = ?", (current_date,)
        ),
        "expired": (
            "SELECT COUNT(*) FROM fridge WHERE expiration_date < ?", (current_date,)
        ),
        "operations_today": (
            "SELECT COUNT(*) FROM operations WHERE created_at >= ?", (current_date,)
        ),
        "errors_today": (
            "SELECT COUNT(*) FROM errors WHERE created_at >= ?", (current_date,)
        ),
    }
    with db.cursor() as cursor:
        result = {}
        for key, (sql, params) in queries.items():
            cursor.execute(sql, params)
            result[key] = int(cursor.fetchone()[0])
        return result
