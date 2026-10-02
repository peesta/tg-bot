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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_hash TEXT,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'employee')),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_login TEXT
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
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_notifications (
    user_id INTEGER PRIMARY KEY,
    last_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT,
    ip TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
    ON users(username COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_operations_created_at
    ON operations(created_at);

CREATE INDEX IF NOT EXISTS idx_operations_created_by
    ON operations(created_by);
"""

SYSTEM_USER_ID = 0
USER_ROLES = ("admin", "employee")
OPERATION_TYPES = ("delivery", "defrost", "sale", "write_off")
# Журнал действий только читается: иначе в нём можно было бы скрыть правки.
READ_ONLY_TABLES = ("audit_log",)


def normalize_text(text: object) -> str | None:
    """Текст для поиска без учёта регистра и разницы между «е» и «ё».

    Подключается к SQLite функцией normalize(): встроенные LOWER и LIKE
    не понимают регистр кириллицы.
    """
    if text is None:
        return None
    return str(text).casefold().replace("ё", "е")


def quote_identifier(name: str) -> str:
    """Название таблицы или столбца для подстановки в SQL."""
    return '"' + name.replace('"', '""') + '"'


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
            self._migrate(connection)
            connection.executescript(DATABASE_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
        return [
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({quote_identifier(table)})"
            )
        ]

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Переводит базу Telegram-бота на схему сайта.

        Пользователь бота сохраняет номер (бывший Telegram ID), поэтому
        журнал операций по-прежнему показывает его имя. Логин у него
        вида tg123456789, пароля нет: войти он сможет, когда администратор
        задаст пароль.
        """
        if "telegram_id" in self._columns(connection, "users"):
            # Переименование столбца обновляет и ссылку из operations.
            connection.execute(
                "ALTER TABLE users RENAME COLUMN telegram_id TO id"
            )
            for column in ("username", "password_hash", "last_login"):
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
            connection.execute("UPDATE users SET username = 'tg' || id")

        if "telegram_id" in self._columns(connection, "daily_notifications"):
            connection.execute(
                "ALTER TABLE daily_notifications "
                "RENAME COLUMN telegram_id TO user_id"
            )

        error_columns = self._columns(connection, "errors")
        if error_columns and "created_at" not in error_columns:
            connection.execute("ALTER TABLE errors ADD COLUMN created_at TEXT")
        connection.commit()

    def get_conn(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path_to_db)
        connection.row_factory = sqlite3.Row
        connection.create_function(
            "normalize", 1, normalize_text, deterministic=True
        )
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
                    freezer_storage_time, category
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
                    freezer_storage_time, category
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
        fridge_storage_time: int,
        freezer_storage_time: int | None = None,
        category: str | None = None,
    ) -> None:
        """Добавляет в таблицу продуктов новые продукты"""
        self._validate_quantity(fridge_storage_time)
        if freezer_storage_time is not None:
            self._validate_quantity(freezer_storage_time)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO products (
                        name, fridge_storage_time, freezer_storage_time,
                        category
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, fridge_storage_time, freezer_storage_time, category),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"{name} уже есть в базе данных")
            
            return

    def update_product(
        self,
        name: str,
        new_name: str,
        fridge_storage_time: int,
        freezer_storage_time: int | None,
        category: str | None,
    ) -> None:
        """Записывает все поля товара; None очищает необязательные поля.

        При переименовании название меняется и у остатков в морозильнике
        и холодильнике, как в edit_product.
        """
        self._validate_quantity(fridge_storage_time)
        if freezer_storage_time is not None:
            self._validate_quantity(freezer_storage_time)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE products
                    SET name = ?, fridge_storage_time = ?,
                        freezer_storage_time = ?, category = ?
                    WHERE name = ?
                    """,
                    (
                        new_name, fridge_storage_time, freezer_storage_time,
                        category, name,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"Нет продукта с именем {name}")

                if new_name != name:
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

    def catalog(self) -> list[dict]:
        """Справочник товаров с остатком в морозильнике, по названию."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT products.rowid AS id, products.name,
                    products.fridge_storage_time,
                    products.freezer_storage_time, products.category,
                    COALESCE(freezer.quantity, 0) AS freezer_quantity
                FROM products
                LEFT JOIN freezer ON freezer.product_name = products.name
                ORDER BY products.name ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def freezer_items(self) -> list[dict]:
        """Остатки морозильника со сроком хранения после разморозки."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT freezer.rowid AS id, freezer.product_name,
                    freezer.quantity, products.fridge_storage_time
                FROM freezer
                LEFT JOIN products ON products.name = freezer.product_name
                ORDER BY freezer.product_name ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

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

    def get_user(self, user_id: int) -> dict | None:
        """Возвращает пользователя (вместе с хешем пароля) или None."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, full_name, role,
                    is_active, last_login
                FROM users
                WHERE id = ?
                """,
                (user_id,)
            )
            return self._user_from_row(cursor.fetchone())

    def get_user_by_username(self, username: str) -> dict | None:
        """Возвращает пользователя по логину без учёта регистра или None."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, full_name, role,
                    is_active, last_login
                FROM users
                WHERE username = ? COLLATE NOCASE
                """,
                (username,)
            )
            return self._user_from_row(cursor.fetchone())

    def users_list(self) -> list[dict]:
        """Возвращает всех пользователей: сначала администраторы."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, full_name, role, is_active, last_login,
                    password_hash IS NOT NULL AS has_password
                FROM users
                ORDER BY role = 'admin' DESC, full_name ASC
                """
            )
            return [self._user_from_row(row) for row in cursor.fetchall()]

    def active_users_ids(self) -> list[int]:
        """Возвращает id всех пользователей с доступом."""
        with self.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE is_active")
            return [row["id"] for row in cursor.fetchall()]

    def has_login_users(self) -> bool:
        """Есть ли хоть один пользователь, который может войти на сайт."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM users WHERE password_hash IS NOT NULL LIMIT 1"
            )
            return cursor.fetchone() is not None

    def add_user(
        self,
        username: str,
        full_name: str,
        password_hash: str | None,
        role: str = "employee"
    ) -> int:
        """Добавляет пользователя с доступом к сайту и возвращает его id."""
        self._validate_role(role)

        with self.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, full_name, role, is_active
                    )
                    VALUES (?, ?, ?, ?, TRUE)
                    """,
                    (username, password_hash, full_name, role),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Логин {username} уже занят")
            return cursor.lastrowid

    def _update_user(self, user_id: int, column: str, value: object) -> None:
        with self.cursor() as cursor:
            try:
                cursor.execute(
                    f"UPDATE users SET {column} = ? WHERE id = ?",
                    (value, user_id),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Логин {value} уже занят")
            if cursor.rowcount == 0:
                raise ValueError(f"Нет пользователя {user_id}")

    def set_user_role(self, user_id: int, role: str) -> None:
        """Назначает пользователю роль admin или employee."""
        self._validate_role(role)
        self._update_user(user_id, "role", role)

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        """Включает или отключает пользователю доступ к сайту."""
        self._update_user(user_id, "is_active", bool(is_active))

    def set_user_password(self, user_id: int, password_hash: str) -> None:
        self._update_user(user_id, "password_hash", password_hash)

    def set_user_name(self, user_id: int, full_name: str) -> None:
        self._update_user(user_id, "full_name", full_name)

    def set_user_username(self, user_id: int, username: str) -> None:
        self._update_user(user_id, "username", username)

    def touch_last_login(self, user_id: int) -> None:
        self._update_user(user_id, "last_login", now_text())

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
                LEFT JOIN users ON users.id = operations.created_by
                WHERE operations.operation_type = 'write_off'
                ORDER BY operations.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            return page_count, [dict(row) for row in cursor.fetchall()]

    def mark_daily_notification(self, user_id: int, date: str) -> bool:
        """Отмечает, что пользователь получил уведомление за дату date.

        Возвращает True, если за этот день отметки ещё не было, — то есть
        уведомление нужно отправить. Проверка и отметка выполняются одним
        запросом, поэтому два одновременных нажатия не дадут двух уведомлений.
        """
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO daily_notifications (user_id, last_date)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE
                    SET last_date = excluded.last_date
                    WHERE daily_notifications.last_date <> excluded.last_date
                """,
                (user_id, date),
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
        работают ссылки и формы на уже открытых страницах сайта. Партии
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

    def restore(self, path: str) -> None:
        """Заменяет базу данных копией из файла path.

        Копия от Telegram-бота переводится на схему сайта.
        """
        source = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            try:
                source.execute("SELECT name FROM sqlite_master").fetchall()
            except sqlite3.DatabaseError as error:
                raise ValueError(f"Файл не похож на базу данных: {error}")
            target = sqlite3.connect(self.path_to_db)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        self._initialize_database()

    def log_error(self, error_type: str, error_message: str) -> None:
        """Записывает ошибку в таблицу errors."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO errors (error_type, error_message, created_at)
                VALUES (?, ?, ?)
                """,
                (error_type, error_message, now_text()),
            )

    @staticmethod
    def _page(
        cursor: sqlite3.Cursor,
        select: str,
        where: str,
        params: list,
        order: str,
        page: int,
        limit: int,
    ) -> tuple[int, list[dict]]:
        """Число строк и строки страницы page (страницы с единицы)."""
        cursor.execute(f"SELECT COUNT(*) {where}", params)
        total = int(cursor.fetchone()[0])
        cursor.execute(
            f"{select} {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, (max(page, 1) - 1) * limit],
        )
        return total, [dict(row) for row in cursor.fetchall()]

    def errors_list(self, page: int = 1, limit: int = 20) -> tuple[int, list[dict]]:
        """Ошибки сайта, новые первыми: (всего, строки страницы)."""
        with self.cursor() as cursor:
            return self._page(
                cursor,
                "SELECT id, error_type, error_message, created_at",
                "FROM errors", [], "id DESC", page, limit,
            )

    def log_action(
        self,
        action: str,
        details: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
        ip: str | None = None,
    ) -> None:
        """Записывает действие пользователя сайта в журнал audit_log."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_log (
                    created_at, user_id, username, action, details, ip
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_text(), user_id, username, action, details, ip),
            )

    def audit_list(
        self,
        page: int = 1,
        limit: int = 50,
        action: str | None = None,
        query: str | None = None,
    ) -> tuple[int, list[dict]]:
        """Журнал действий, новые первыми: (всего, строки страницы)."""
        conditions, params = [], []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if query:
            conditions.append(
                "(instr(normalize(username), ?) > 0 "
                "OR instr(normalize(details), ?) > 0)"
            )
            params += [normalize_text(query)] * 2
        where = "FROM audit_log"
        if conditions:
            where += " WHERE " + " AND ".join(conditions)

        with self.cursor() as cursor:
            return self._page(
                cursor,
                "SELECT id, created_at, user_id, username, action, details, ip",
                where, params, "id DESC", page, limit,
            )

    def operations_log(
        self,
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
        where = (
            "FROM operations "
            "LEFT JOIN users ON users.id = operations.created_by"
        )
        if conditions:
            where += " WHERE " + " AND ".join(conditions)

        with self.cursor() as cursor:
            return self._page(
                cursor,
                "SELECT operations.id, operations.operation_type, "
                "operations.product_name, operations.batch_id, "
                "operations.quantity, operations.reason, "
                "operations.created_at, operations.created_by, "
                "users.full_name",
                where, params, "operations.id DESC", page, limit,
            )

    def stats(self) -> dict[str, int]:
        """Сводка для главной страницы администратора."""
        today = datetime.now().strftime("%Y-%m-%d")
        queries = {
            "products": ("SELECT COUNT(*) FROM products", ()),
            "freezer_items": ("SELECT COUNT(*) FROM freezer", ()),
            "freezer_quantity": (
                "SELECT COALESCE(SUM(quantity), 0) FROM freezer", ()
            ),
            "fridge_batches": ("SELECT COUNT(*) FROM fridge", ()),
            "fridge_quantity": (
                "SELECT COALESCE(SUM(quantity), 0) FROM fridge", ()
            ),
            "expiring_today": (
                "SELECT COUNT(*) FROM fridge WHERE expiration_date = ?",
                (today,),
            ),
            "expired": (
                "SELECT COUNT(*) FROM fridge WHERE expiration_date < ?",
                (today,),
            ),
            "operations_today": (
                "SELECT COUNT(*) FROM operations WHERE created_at >= ?",
                (today,),
            ),
            "errors_today": (
                "SELECT COUNT(*) FROM errors WHERE created_at >= ?",
                (today,),
            ),
            "active_users": (
                "SELECT COUNT(*) FROM users WHERE is_active", ()
            ),
        }
        with self.cursor() as cursor:
            result = {}
            for key, (sql, params) in queries.items():
                cursor.execute(sql, params)
                result[key] = int(cursor.fetchone()[0])
            return result

    # ---------- Редактор таблиц для администратора ----------

    def table_names(self) -> list[str]:
        """Таблицы базы данных, кроме служебных таблиц SQLite."""
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
            return [row["name"] for row in cursor.fetchall()]

    def _check_table(self, table: str) -> None:
        if table not in self.table_names():
            raise KeyError(table)

    def table_columns(self, table: str) -> list[dict]:
        """Столбцы таблицы: name, type, notnull, default, pk."""
        self._check_table(table)
        with self.cursor() as cursor:
            cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
            return [
                {
                    "name": row["name"],
                    "type": (row["type"] or "").upper(),
                    "notnull": bool(row["notnull"]),
                    "default": row["dflt_value"],
                    "pk": bool(row["pk"]),
                }
                for row in cursor.fetchall()
            ]

    def table_count(self, table: str) -> int:
        self._check_table(table)
        with self.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
            return int(cursor.fetchone()[0])

    def table_rows(
        self,
        table: str,
        page: int = 1,
        limit: int = 50,
        query: str | None = None,
        sort: str | None = None,
        descending: bool = False,
    ) -> tuple[int, list[dict]]:
        """Строки таблицы с поиском по всем столбцам: (всего, строки).

        У каждой строки есть ключ __rowid — по нему строку редактируют.
        """
        columns = [column["name"] for column in self.table_columns(table)]
        params: list = []
        where = f"FROM {quote_identifier(table)}"
        if query:
            where += " WHERE " + " OR ".join(
                f"instr(normalize({quote_identifier(name)}), ?) > 0"
                for name in columns
            )
            params = [normalize_text(query)] * len(columns)
        order = quote_identifier(sort) if sort in columns else "rowid"
        order += " DESC" if descending else " ASC"

        with self.cursor() as cursor:
            return self._page(
                cursor, "SELECT rowid AS __rowid, *", where, params,
                order, page, limit,
            )

    def table_row(self, table: str, rowid: int) -> dict | None:
        self._check_table(table)
        with self.cursor() as cursor:
            cursor.execute(
                f"SELECT rowid AS __rowid, * FROM {quote_identifier(table)} "
                "WHERE rowid = ?",
                (rowid,),
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def _check_writable(self, table: str, values: dict) -> list[str]:
        if table in READ_ONLY_TABLES:
            raise ValueError(f"Таблица {table} только для чтения")
        columns = [column["name"] for column in self.table_columns(table)]
        unknown = [name for name in values if name not in columns]
        if unknown:
            raise ValueError(f"Нет столбцов: {', '.join(unknown)}")
        return columns

    def insert_row(self, table: str, values: dict) -> int:
        """Добавляет строку и возвращает её rowid."""
        self._check_writable(table, values)
        names = ", ".join(map(quote_identifier, values))
        marks = ", ".join("?" for _ in values)
        sql = (
            f"INSERT INTO {quote_identifier(table)} ({names}) VALUES ({marks})"
            if values else
            f"INSERT INTO {quote_identifier(table)} DEFAULT VALUES"
        )
        with self.cursor() as cursor:
            try:
                cursor.execute(sql, list(values.values()))
            except sqlite3.Error as error:
                raise ValueError(f"База данных не приняла строку: {error}")
            return cursor.lastrowid

    def update_row(self, table: str, rowid: int, values: dict) -> None:
        self._check_writable(table, values)
        if not values:
            return
        assignments = ", ".join(f"{quote_identifier(name)} = ?" for name in values)
        with self.cursor() as cursor:
            try:
                cursor.execute(
                    f"UPDATE {quote_identifier(table)} SET {assignments} "
                    "WHERE rowid = ?",
                    [*values.values(), rowid],
                )
            except sqlite3.Error as error:
                raise ValueError(f"База данных не приняла изменения: {error}")
            if cursor.rowcount == 0:
                raise ValueError("Строка не найдена: возможно, её уже удалили")

    def delete_row(self, table: str, rowid: int) -> None:
        self._check_writable(table, {})
        with self.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {quote_identifier(table)} WHERE rowid = ?",
                (rowid,),
            )
            if cursor.rowcount == 0:
                raise ValueError("Строка не найдена: возможно, её уже удалили")
