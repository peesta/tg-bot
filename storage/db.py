import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator


DATABASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    name TEXT PRIMARY KEY,
    fridge_storage_time INTEGER,
    freezer_storage_time INTEGER,
    category TEXT
);

CREATE TABLE IF NOT EXISTS fridge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    date_added TEXT NOT NULL,
    expiration_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS freezer (
    product_name TEXT PRIMARY KEY,
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'employee')),
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type TEXT NOT NULL
        CHECK (operation_type IN ('delivery', 'defrost', 'sale', 'write_off')),
    product_name TEXT NOT NULL,
    batch_id INTEGER,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    reason TEXT,
    created_at TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES fridge(id),
    FOREIGN KEY (created_by) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operations_created_at
    ON operations(created_at);

CREATE INDEX IF NOT EXISTS idx_operations_created_by
    ON operations(created_by);
"""

SYSTEM_USER_ID = 0


class Database:
    def __init__(self, path_to_db: str = "data/database.db") -> None:
        self.path_to_db = path_to_db
        self._create_database_directory()
        self._initialize_database()

    def _create_database_directory(self) -> None:
        if self.path_to_db == ":memory:":
            raise ValueError("Database поддерживает только файловые базы данных")
        Path(self.path_to_db).parent.mkdir(parents=True, exist_ok=True)

    def _initialize_database(self) -> None:
        connection = self.get_conn()
        try:
            connection.executescript(DATABASE_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def get_conn(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path_to_db)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        connection = self.get_conn()
        cursor = connection.cursor()
        try:
            yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        is_integer = isinstance(quantity, int) and not isinstance(
            quantity, bool
        )
        if not is_integer or quantity <= 0:
            raise ValueError("Количество должно быть положительным целым числом")

    @staticmethod
    def _operation_user_id(user_id: int | None) -> int:
        return SYSTEM_USER_ID if user_id is None else user_id

    def _log_operation(
        self,
        cursor: sqlite3.Cursor,
        operation_type: str,
        product_name: str,
        quantity: int,
        user_id: int | None,
        batch_id: int | None = None,
        reason: str | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO operations (
                operation_type,
                product_name,
                batch_id,
                quantity,
                reason,
                created_at,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_type,
                product_name,
                batch_id,
                quantity,
                reason,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                self._operation_user_id(user_id),
            ),
        )

    def move_to_fridge(
        self, product_name: str, quantity: int, user_id: int | None = None
    ) -> str:
        """Перемещает указанное количество продукта в холодильник."""
        self._validate_quantity(quantity)

        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT quantity FROM freezer WHERE product_name = ?
                """,
                (product_name,),
            )

            freezer_row = cursor.fetchone()
            if freezer_row is None:
                raise ValueError(f"Нет {product_name} в морозильнике")

            freezer_quantity = freezer_row["quantity"]
            if freezer_quantity < quantity:
                raise ValueError(f"Недостаточно {product_name} в морозильнике")

            cursor.execute(
                """
                SELECT fridge_storage_time FROM products WHERE name = ?
                """,
                (product_name,),
            )
            product = cursor.fetchone()

            if product is None:
                raise ValueError(f"Продукт {product_name} не найден в базе данных")

            fridge_storage_time = product["fridge_storage_time"]
            added_at = datetime.now()
            date_added = added_at.strftime("%Y-%m-%d")
            expiration_date = (
                added_at + timedelta(days=fridge_storage_time)
            ).strftime("%Y-%m-%d")

            cursor.execute(
                """
                INSERT INTO fridge (
                    product_name,
                    quantity,
                    date_added,
                    expiration_date
                )
                VALUES (?, ?, ?, ?)
                """,
                (product_name, quantity, date_added, expiration_date),
            )

            batch_id = cursor.lastrowid

            if freezer_quantity == quantity:
                cursor.execute(
                    "DELETE FROM freezer WHERE product_name = ?",
                    (product_name,),
                )
            else:
                cursor.execute(
                    "UPDATE freezer SET quantity = ? WHERE product_name = ?",
                    (freezer_quantity - quantity, product_name),
                )

            self._log_operation(
                cursor=cursor,
                operation_type="defrost",
                product_name=product_name,
                quantity=quantity,
                user_id=user_id,
                batch_id=batch_id,
            )

            return (
                f"Успешно добавлено {quantity} {product_name} в холодильник"
            )

    def get_expiring_products(
        self,
    ) -> tuple[list[dict[int, str, int]], list[dict[int, str, int]]]:
        """Возвращает просроченные и истекающие сегодня партии."""
        with self.cursor() as cursor:
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT id, product_name, quantity, expiration_date
                FROM fridge
                WHERE expiration_date <= ?
                """,
                (today,),
            )
            batches = cursor.fetchall()

            if not batches:
                return None

            expired_products: list[dict[int, str, int]] = []
            expiring_today: list[dict[str, int]] = []

            for batch in batches:
                batch_summary = {
                    "id": batch["id"],
                    "product_name": batch["product_name"],
                    "quantity": batch["quantity"],
                }
                if batch["expiration_date"] < today:
                    expired_products.append(batch_summary)
                else:
                    expiring_today.append(batch_summary)

            return expired_products, expiring_today

    def clear_expired_product(
        self,
        id: int | None = None,
        name: str | None = None,
        quantity: int | None = None,
        operation_type: str = "write_off",
        user_id: int | None = None,
        reason: str | None = None
    ) -> str | bool:
        """Списывает одну партию или всю просрочку при вызове без партии."""
        no_batch_arguments = id is None and name is None and quantity is None
        if no_batch_arguments:
            return self._clear_all_expired_products(user_id)

        if id is None or quantity is None:
            raise ValueError("Для списания одной партии нужны id и quantity")

        self._validate_quantity(quantity)
        return self._clear_fridge_batch(
            batch_id=id,
            quantity=quantity,
            operation_type=operation_type,
            user_id=user_id,
            reason=reason
        )

    def _clear_all_expired_products(
        self,
        user_id: int | None,
    ) -> str | bool:
        with self.cursor() as cursor:
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT id, product_name, quantity
                FROM fridge
                WHERE expiration_date <= ?
                ORDER BY id
                """,
                (today,),
            ) #Продукты всегда списываются в конце смены, метод списывает и сегодняшние продукты
            expired_batches = cursor.fetchall()

            if not expired_batches:
                return False

            for batch in expired_batches:
                self._log_operation(
                    cursor=cursor,
                    operation_type="write_off",
                    product_name=batch["product_name"],
                    quantity=batch["quantity"],
                    user_id=user_id,
                    batch_id=batch["id"],
                    reason="Просрочено",
                )

            batch_ids = [(batch["id"],) for batch in expired_batches]
            cursor.executemany(
                "DELETE FROM fridge WHERE id = ?",
                batch_ids,
            )

            total_quantity = sum(
                batch["quantity"] for batch in expired_batches
            )
            return (
                f"Списано просроченных партий: {len(expired_batches)}. "
                f"Общее количество продуктов: {total_quantity} Шт."
            )

    def _clear_fridge_batch(
        self,
        batch_id: int,
        quantity: int,
        operation_type: str | None,
        user_id: int | None,
        reason: str | None
    ) -> str | bool:
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_name, quantity
                FROM fridge
                WHERE id = ?
                """,
                (batch_id,),
            )
            batch = cursor.fetchone()

            if batch is None:
                return False

            product_name = batch["product_name"]
            current_quantity = batch["quantity"]
            if quantity > current_quantity:
                return False

            logged_operation_type, reason = self._operation_details(
                operation_type, reason=reason
            )
            self._log_operation(
                cursor=cursor,
                operation_type=logged_operation_type,
                product_name=product_name,
                quantity=quantity,
                user_id=user_id,
                batch_id=batch_id,
                reason=reason,
            )

            remaining_quantity = current_quantity - quantity
            if remaining_quantity > 0:
                cursor.execute(
                    """
                    UPDATE fridge
                    SET quantity = ?
                    WHERE id = ?
                    """,
                    (remaining_quantity, batch_id),
                )
                return (
                    f"Списана партия {product_name} - {quantity} Шт. "
                    f"Осталось {remaining_quantity} Шт. "
                    f"Причина {operation_type}"
                )

            cursor.execute(
                "DELETE FROM fridge WHERE id = ?",
                (batch_id,),
            )
            return (
                f"Партия {product_name} - {quantity} Шт. списана "
                f"полностью по причине {operation_type}"
            )

    @staticmethod
    def _operation_details(
        operation_type: str | None,
        reason: str | None
    ) -> tuple[str, str | None]:
        if operation_type in (None, "write_off") and reason is not None:
            return "write_off", reason

        if operation_type == "sale":
            return "sale", None

        # В старых вызовах четвёртым аргументом передавалась причина списания.
        return "write_off", operation_type

    def new_delivery(
        self, 
        product_name: str, 
        quantity: int, 
        user_id: int | None = None
    ) -> str:
        """Добавляет поставку продукта в морозильник."""
        self._validate_quantity(quantity)

        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO freezer (product_name, quantity)
                VALUES (?, ?)
                ON CONFLICT(product_name) DO UPDATE SET
                    quantity = freezer.quantity + excluded.quantity
                """,
                (product_name, quantity),
            )

            self._log_operation(
                cursor=cursor,
                operation_type="delivery",
                product_name=product_name,
                quantity=quantity,
                user_id=user_id,
            )

            return (
                f"Успешно добавлено {quantity} {product_name} в морозильник"
            )

    def fridge_batches_list(
        self, 
        isfresh: bool = False
        ) -> list[dict]:
        """Возвращает партии холодильника по сроку годности. Можно выбрать отдельно только свежие партии"""
        with self.cursor() as cursor:
            if isfresh: 
                today = datetime.now().strftime("%Y-%m-%d")
                cursor.execute(
                    """
                    SELECT id, product_name, quantity, date_added, expiration_date 
                    FROM fridge 
                    WHERE expiration_date > ? 
                    ORDER BY expiration_date ASC
                    """,
                    (today,)
                )
                
                return [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT id, product_name, quantity, date_added, expiration_date 
                FROM fridge 
                ORDER BY expiration_date ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def _get_page_count(self, cursor: sqlite3.Cursor) -> int:
        """Возвращает количество страниц для холодильника."""
        cursor.execute(
            """
            SELECT COUNT(*) FROM freezer
            """
        )
        return int(cursor.fetchone()[0])

    def freezer_products_list(self, page: int = 1, limit: int = 3) -> list[dict]:
        """Возвращает текущие остатки продуктов в морозильнике."""
        offset = (page - 1) * limit
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_name, quantity 
                FROM freezer
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            if page == 1:
                page_count = self._get_page_count(cursor=cursor)
                return page_count, [dict(row) for row in cursor.fetchall()]
            return [dict(row) for row in cursor.fetchall()]

    def get_freezer_product(self, product_name: str) -> dict | None:
        """Возвращает информацию о конкретном продукте в морозильнике."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT quantity 
                FROM freezer
                WHERE product_name = ?
                """,
                (product_name,)
            )
            result = cursor.fetchone()
            if result is None:
                return ValueError(f"Продукт не найден")
            return {"product_name": product_name, "quantity": int(result[0])}

    def new_product(
        self, 
        name: str, 
        fridge_storage_time: int
    ) -> None:
        """Добавляет в таблицу продуктов новые продукты"""
        self._validate_quantity(fridge_storage_time)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO products (name, fridge_storage_time)
                    VALUES (?,?)
                    """, (name, fridge_storage_time),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"{name} уже есть в базе данных")
            
            return

    def edit_product(
        self,
        name: str,
        fridge_storage_time: int,
        freezer_storage_time: int,
        new_name: str | None = None
    ) -> None:
        self._validate_quantity(fridge_storage_time)
        self._validate_quantity(freezer_storage_time)

        with self.cursor() as cursor:

            request = """
                UPDATE products 
                SET fridge_storage_time = ?
                SET freezer_storage_time = ?
                """
            params = (fridge_storage_time, freezer_storage_time)

            if new_name is not None:
                request += " SET name = ?"
                params.append(new_name)

            request += " WHERE name = ?"
            params.append(name)

            try:
                cursor.execute(request, params)
            except sqlite3.IntegrityError:
                raise ValueError()
            if cursor.fetchone is None:
                raise ValueError(f"Нет продукта с именем {name}")

            return
