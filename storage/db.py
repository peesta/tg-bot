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

CREATE TABLE IF NOT EXISTS daily_notifications (
    telegram_id INTEGER PRIMARY KEY,
    last_date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operations_created_at
    ON operations(created_at);

CREATE INDEX IF NOT EXISTS idx_operations_created_by
    ON operations(created_by);
"""

SYSTEM_USER_ID = 0
USER_ROLES = ("admin", "employee")


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
    ) -> dict:
        """Перемещает указанное количество продукта в холодильник.

        Возвращает созданную партию: id, product_name, quantity, date_added,
        expiration_date.
        """
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

            return {
                "id": batch_id,
                "product_name": product_name,
                "quantity": quantity,
                "date_added": date_added,
                "expiration_date": expiration_date,
            }

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

            action = "Продано" if logged_operation_type == "sale" else "Списано"
            details = f"Причина: {reason}. " if reason else ""

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
                    f"{action}: {product_name} - {quantity} Шт. {details}"
                    f"Осталось в партии {remaining_quantity} Шт."
                )

            cursor.execute(
                "DELETE FROM fridge WHERE id = ?",
                (batch_id,),
            )
            return (
                f"{action}: {product_name} - {quantity} Шт. {details}"
                f"Партия закрыта полностью."
            )

    @staticmethod
    def _operation_details(
        operation_type: str | None,
        reason: str | None
    ) -> tuple[str, str | None]:
        if operation_type in (None, "write_off"):
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

    def get_fridge_batch(self, batch_id: int) -> dict | None:
        """Возвращает партию холодильника по id или None."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, product_name, quantity, date_added, expiration_date
                FROM fridge
                WHERE id = ?
                """,
                (batch_id,)
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def search_fridge_batches(self, query: str, limit: int = 10) -> list[dict]:
        """Ищет партии холодильника по части названия продукта."""
        rows = [
            batch for batch in self.fridge_batches_list()
            if self._matches(batch["product_name"], query)
        ]
        return rows[:limit]

    @staticmethod
    def _count_pages(total: int, limit: int) -> int:
        return (total + limit - 1) // limit

    def _get_page_count(
        self,
        cursor: sqlite3.Cursor,
        limit: int = 3,
        table: str = "freezer"
    ) -> int:
        """Возвращает количество страниц таблицы (0, если таблица пуста)."""
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return self._count_pages(int(cursor.fetchone()[0]), limit)

    @staticmethod
    def _matches(name: str, query: str) -> bool:
        """Поиск без учёта регистра и разницы между «е» и «ё»."""
        def normalize(text: str) -> str:
            return text.casefold().replace("ё", "е")

        return normalize(query) in normalize(name)

    def freezer_products_list(
        self,
        page: int = 1,
        limit: int = 3
    ) -> tuple[int | None, list[dict] | None]:
        """Возвращает количество страниц и страницу остатков морозильника.

        (0, None) — морозильник пуст, (None, None) — такой страницы нет.
        """
        with self.cursor() as cursor:
            page_count = self._get_page_count(cursor=cursor, limit=limit)
            if page_count == 0:
                return 0, None
            if page < 1 or page > page_count:
                return None, None

            offset = (page - 1) * limit
            cursor.execute(
                """
                SELECT rowid AS id, product_name, quantity
                FROM freezer
                ORDER BY product_name ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            return page_count, [dict(row) for row in cursor.fetchall()]

    def search_freezer_products(self, query: str, limit: int = 10) -> list[dict]:
        """Ищет продукты морозильника по части названия."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, product_name, quantity
                FROM freezer
                ORDER BY product_name ASC
                """
            )
            rows = [
                dict(row) for row in cursor.fetchall()
                if self._matches(row["product_name"], query)
            ]
            return rows[:limit]

    def get_freezer_product(self, product_name: str) -> dict | None:
        """Возвращает информацию о конкретном продукте в морозильнике."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, product_name, quantity
                FROM freezer
                WHERE product_name = ?
                """,
                (product_name,)
            )
            result = cursor.fetchone()
            if result is None:
                return None
            return dict(result)

    def get_freezer_product_by_id(self, product_id: int) -> dict | None:
        """Возвращает продукт морозильника по id из freezer_products_list."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, product_name, quantity
                FROM freezer
                WHERE rowid = ?
                """,
                (product_id,)
            )
            result = cursor.fetchone()
            return None if result is None else dict(result)

    def products_list(
        self,
        page: int = 1,
        limit: int = 5
    ) -> tuple[int | None, list[dict] | None]:
        """Возвращает количество страниц и страницу справочника продуктов.

        (0, None) — справочник пуст, (None, None) — такой страницы нет.
        """
        with self.cursor() as cursor:
            page_count = self._get_page_count(
                cursor=cursor, limit=limit, table="products"
            )
            if page_count == 0:
                return 0, None
            if page < 1 or page > page_count:
                return None, None

            offset = (page - 1) * limit
            cursor.execute(
                """
                SELECT rowid AS id, name, fridge_storage_time,
                    freezer_storage_time
                FROM products
                ORDER BY name ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            return page_count, [dict(row) for row in cursor.fetchall()]

    def search_products(self, query: str, limit: int = 10) -> list[dict]:
        """Ищет продукты справочника по части названия."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, name, fridge_storage_time,
                    freezer_storage_time
                FROM products
                ORDER BY name ASC
                """
            )
            rows = [
                dict(row) for row in cursor.fetchall()
                if self._matches(row["name"], query)
            ]
            return rows[:limit]

    def get_product(self, name: str) -> dict | None:
        """Возвращает продукт справочника по названию."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, name, fridge_storage_time,
                    freezer_storage_time
                FROM products
                WHERE name = ?
                """,
                (name,)
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def get_product_by_id(self, product_id: int) -> dict | None:
        """Возвращает продукт справочника по id из products_list."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid AS id, name, fridge_storage_time,
                    freezer_storage_time
                FROM products
                WHERE rowid = ?
                """,
                (product_id,)
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

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
        freezer_storage_time: int | None = None,
        new_name: str | None = None
    ) -> None:
        """Меняет сроки хранения продукта и, если нужно, его название.

        Если freezer_storage_time не передан, прежнее значение сохраняется.
        При переименовании название меняется и у остатков в морозильнике
        и холодильнике, иначе их нельзя будет разморозить или найти.
        """
        self._validate_quantity(fridge_storage_time)
        if freezer_storage_time is not None:
            self._validate_quantity(freezer_storage_time)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE products
                    SET fridge_storage_time = ?,
                        freezer_storage_time = COALESCE(?, freezer_storage_time),
                        name = ?
                    WHERE name = ?
                    """,
                    (
                        fridge_storage_time,
                        freezer_storage_time,
                        new_name or name,
                        name,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"Нет продукта с именем {name}")

                if new_name is not None and new_name != name:
                    cursor.execute(
                        "UPDATE freezer SET product_name = ? WHERE product_name = ?",
                        (new_name, name),
                    )
                    cursor.execute(
                        "UPDATE fridge SET product_name = ? WHERE product_name = ?",
                        (new_name, name),
                    )
            except sqlite3.IntegrityError:
                raise ValueError(f"{new_name} уже есть в базе данных")

            return

    def delete_product(self, name: str) -> None:
        """Удаляет продукт из справочника.

        Продукт с остатком в морозильнике удалить нельзя: без справочника
        его не получится разморозить.
        """
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT quantity FROM freezer WHERE product_name = ?",
                (name,),
            )
            if cursor.fetchone() is not None:
                raise ValueError(
                    f"{name} ещё есть в морозильнике, сначала разморозьте "
                    f"остаток"
                )

            cursor.execute("DELETE FROM products WHERE name = ?", (name,))
            if cursor.rowcount == 0:
                raise ValueError(f"Нет продукта с именем {name}")

    @staticmethod
    def _user_from_row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        user = dict(row)
        user["is_active"] = bool(user["is_active"])
        return user

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in USER_ROLES:
            raise ValueError(f"Неизвестная роль {role}")

    def get_user(self, telegram_id: int) -> dict | None:
        """Возвращает пользователя по Telegram ID или None."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT telegram_id, full_name, role, is_active
                FROM users
                WHERE telegram_id = ?
                """,
                (telegram_id,)
            )
            return self._user_from_row(cursor.fetchone())

    def users_list(self) -> list[dict]:
        """Возвращает всех пользователей: сначала администраторы."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT telegram_id, full_name, role, is_active
                FROM users
                ORDER BY role = 'admin' DESC, full_name ASC
                """
            )
            return [self._user_from_row(row) for row in cursor.fetchall()]

    def active_users_ids(self) -> list[int]:
        """Возвращает Telegram ID всех пользователей с доступом."""
        with self.cursor() as cursor:
            cursor.execute("SELECT telegram_id FROM users WHERE is_active")
            return [row["telegram_id"] for row in cursor.fetchall()]

    def add_user(
        self,
        telegram_id: int,
        full_name: str,
        role: str = "employee"
    ) -> None:
        """Добавляет пользователя с доступом к боту."""
        self._validate_role(role)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO users (telegram_id, full_name, role, is_active)
                    VALUES (?, ?, ?, TRUE)
                    """,
                    (telegram_id, full_name, role),
                )
            except sqlite3.IntegrityError:
                raise ValueError(
                    f"Пользователь {telegram_id} уже есть в базе данных"
                )

    def set_user_role(self, telegram_id: int, role: str) -> None:
        """Назначает пользователю роль admin или employee."""
        self._validate_role(role)

        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET role = ? WHERE telegram_id = ?",
                (role, telegram_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Нет пользователя {telegram_id}")

    def set_user_active(self, telegram_id: int, is_active: bool) -> None:
        """Включает или отключает пользователю доступ к боту."""
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET is_active = ? WHERE telegram_id = ?",
                (bool(is_active), telegram_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Нет пользователя {telegram_id}")

    def write_off_history(
        self,
        page: int = 1,
        limit: int = 10
    ) -> tuple[int | None, list[dict] | None]:
        """Возвращает количество страниц и страницу журнала списаний.

        Новые записи идут первыми. (0, None) — списаний не было,
        (None, None) — такой страницы нет.
        """
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM operations
                WHERE operation_type = 'write_off'
                """
            )
            page_count = self._count_pages(int(cursor.fetchone()[0]), limit)
            if page_count == 0:
                return 0, None
            if page < 1 or page > page_count:
                return None, None

            offset = (page - 1) * limit
            cursor.execute(
                """
                SELECT operations.id, operations.product_name,
                    operations.quantity, operations.reason,
                    operations.created_at, operations.created_by,
                    users.full_name
                FROM operations
                LEFT JOIN users ON users.telegram_id = operations.created_by
                WHERE operations.operation_type = 'write_off'
                ORDER BY operations.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            return page_count, [dict(row) for row in cursor.fetchall()]

    def mark_daily_notification(self, telegram_id: int, date: str) -> bool:
        """Отмечает, что пользователь получил уведомление за дату date.

        Возвращает True, если за этот день отметки ещё не было, — то есть
        уведомление нужно отправить. Проверка и отметка выполняются одним
        запросом, поэтому два одновременных нажатия не дадут двух уведомлений.
        """
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO daily_notifications (telegram_id, last_date)
                VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE
                    SET last_date = excluded.last_date
                    WHERE daily_notifications.last_date <> excluded.last_date
                """,
                (telegram_id, date),
            )
            return cursor.rowcount > 0

    def stock_tables(self) -> dict[str, list[dict]]:
        """Возвращает все строки таблиц products, freezer и fridge."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT name, fridge_storage_time, freezer_storage_time, category
                FROM products
                ORDER BY name ASC
                """
            )
            products = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT product_name, quantity
                FROM freezer
                ORDER BY product_name ASC
                """
            )
            freezer = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT id, product_name, quantity, date_added, expiration_date
                FROM fridge
                ORDER BY expiration_date ASC, id ASC
                """
            )
            fridge = [dict(row) for row in cursor.fetchall()]

            return {"products": products, "freezer": freezer, "fridge": fridge}

    def replace_stock_tables(
        self,
        products: list[dict],
        freezer: list[dict],
        fridge: list[dict],
    ) -> None:
        """Заменяет содержимое products, freezer и fridge одной транзакцией.

        Строки должны быть уже проверены. Товары и остатки морозильника,
        которые были в базе и раньше, сохраняют свои id (rowid): по ним
        работают кнопки в уже отправленных сообщениях бота. Партии
        холодильника без id получают новый номер.
        """
        with self.cursor() as cursor:
            cursor.execute("SELECT rowid, name FROM products")
            product_ids = {row["name"]: row["rowid"] for row in cursor.fetchall()}
            cursor.execute("SELECT rowid, product_name FROM freezer")
            freezer_ids = {
                row["product_name"]: row["rowid"] for row in cursor.fetchall()
            }

            cursor.execute("DELETE FROM fridge")
            cursor.execute("DELETE FROM freezer")
            cursor.execute("DELETE FROM products")

            next_id = max(product_ids.values(), default=0) + 1
            for product in products:
                rowid = product_ids.get(product["name"])
                if rowid is None:
                    rowid, next_id = next_id, next_id + 1
                cursor.execute(
                    """
                    INSERT INTO products (
                        rowid, name, fridge_storage_time,
                        freezer_storage_time, category
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        rowid,
                        product["name"],
                        product["fridge_storage_time"],
                        product.get("freezer_storage_time"),
                        product.get("category"),
                    ),
                )

            next_id = max(freezer_ids.values(), default=0) + 1
            for item in freezer:
                rowid = freezer_ids.get(item["product_name"])
                if rowid is None:
                    rowid, next_id = next_id, next_id + 1
                cursor.execute(
                    """
                    INSERT INTO freezer (rowid, product_name, quantity)
                    VALUES (?, ?, ?)
                    """,
                    (rowid, item["product_name"], item["quantity"]),
                )

            # Сначала партии с заданным id, чтобы новый номер для партии
            # без id не занял чужой id из таблицы.
            for batch in sorted(fridge, key=lambda batch: batch.get("id") is None):
                cursor.execute(
                    """
                    INSERT INTO fridge (
                        id, product_name, quantity, date_added, expiration_date
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch.get("id"),
                        batch["product_name"],
                        batch["quantity"],
                        batch["date_added"],
                        batch["expiration_date"],
                    ),
                )

    def backup(self, path: str) -> None:
        """Сохраняет копию базы данных в файл path."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        source = self.get_conn()
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def log_error(self, error_type: str, error_message: str) -> None:
        """Записывает ошибку в таблицу errors."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO errors (error_type, error_message)
                VALUES (?, ?)
                """,
                (error_type, error_message),
            )
