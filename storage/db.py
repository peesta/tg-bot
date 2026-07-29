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
            return

        Path(self.path_to_db).parent.mkdir(parents=True, exist_ok=True)

    def _initialize_database(self) -> None:
        connection = self.get_conn()
        try:
            connection.executescript(DATABASE_SCHEMA)
            self._add_missing_operation_columns(connection)
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _add_missing_operation_columns(
        connection: sqlite3.Connection,
    ) -> None:
        operation_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(operations)")
        }
        if "reason" not in operation_columns:
            connection.execute(
                "ALTER TABLE operations ADD COLUMN reason TEXT"
            )

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
            raise ValueError("quantity must be a positive integer")

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
                datetime.now().isoformat(timespec="seconds"),
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
                return f"Нет {product_name} в морозильнике"

            freezer_quantity = freezer_row["quantity"]
            if freezer_quantity < quantity:
                return f"Недостаточно {product_name} в морозильнике"

            cursor.execute(
                """
                SELECT fridge_storage_time FROM products WHERE name = ?
                """,
                (product_name,),
            )
            product = cursor.fetchone()

            if product is None:
                raise ValueError(
                    f"Продукт {product_name} не найден в базе данных"
                )

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
                f"Успешно добавлено {quantity} "
                f"{product_name} в холодильник"
            )

    def get_expiring_products(
        self,
    ) -> tuple[list[tuple[int, str, int]], list[tuple[int, str, int]]] | bool:
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
                return False

            expired_products: list[tuple[int, str, int]] = []
            expiring_today: list[tuple[int, str, int]] = []

            for batch in batches:
                batch_summary = (
                    batch["id"],
                    batch["product_name"],
                    batch["quantity"],
                )
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
        operation_type: str | None = None,
        user_id: int | None = None,
    ) -> str | bool:
        """Списывает одну партию или всю просрочку при вызове без партии."""
        no_batch_arguments = id is None and name is None and quantity is None
        if no_batch_arguments:
            return self._clear_all_expired_products(user_id)

        if id is None or quantity is None:
            raise ValueError(
                "Для списания одной партии нужны id и quantity"
            )

        self._validate_quantity(quantity)
        return self._clear_fridge_batch(
            batch_id=id,
            quantity=quantity,
            operation_type=operation_type,
            user_id=user_id,
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
                WHERE expiration_date < ?
                ORDER BY id
                """,
                (today,),
            )
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
                    reason="expired",
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
                f"Общее количество: {total_quantity} Шт."
            )

    def _clear_fridge_batch(
        self,
        batch_id: int,
        quantity: int,
        operation_type: str | None,
        user_id: int | None,
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
                operation_type
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
    ) -> tuple[str, str | None]:
        if operation_type in (None, "write_off"):
            return "write_off", None

        if operation_type == "sale":
            return "sale", None

        # В старых вызовах четвёртым аргументом передавалась причина списания.
        return "write_off", operation_type

    def new_delivery(
        self, product_name: str, quantity: int, user_id: int | None = None
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
                f"Успешно добавлено {quantity} "
                f"{product_name} в морозильник"
            )

    def fridge_batches_list(self) -> list[sqlite3.Row]:
        """Возвращает партии холодильника по сроку годности."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, product_name, quantity, date_added, expiration_date
                FROM fridge
                ORDER BY expiration_date ASC
                """
            )
            return cursor.fetchall()

    def freezer_products_list(self) -> list[sqlite3.Row]:
        """Возвращает текущие остатки продуктов в морозильнике."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_name, quantity
                FROM freezer
                """
            )
            return cursor.fetchall()


DB = Database()
