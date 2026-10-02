"""Методы storage/db.py, которые вызывает сайт."""
import sqlite3
import unittest

from storage.db import Database
from tests.helpers import TempDatabaseTestCase


class FreezerTest(TempDatabaseTestCase):
    def test_pagination(self):
        self.assertEqual(self.db.freezer_products_list(page=1, limit=3), (0, None))

        for name in ("Медовик", "Филадельфия", "Ёжик"):
            self.db.new_product(name, 2)
            self.db.new_delivery(name, 5)

        page_count, products = self.db.freezer_products_list(page=1, limit=3)
        self.assertEqual(page_count, 1)
        self.assertEqual(len(products), 3)

        self.assertEqual(self.db.freezer_products_list(page=2, limit=2)[0], 2)
        self.assertEqual(len(self.db.freezer_products_list(page=2, limit=2)[1]), 1)
        self.assertEqual(self.db.freezer_products_list(page=3, limit=2), (None, None))
        self.assertEqual(self.db.freezer_products_list(page=0, limit=2), (None, None))
        # Раньше номер страницы сравнивался с limit: 4-я страница не открывалась.
        for index in range(10):
            self.db.new_product(f"Товар {index}", 1)
            self.db.new_delivery(f"Товар {index}", 1)
        self.assertEqual(self.db.freezer_products_list(page=5, limit=3)[0], 5)

    def test_search_ignores_case_and_yo(self):
        for name in ("Ёжик", "Филадельфия"):
            self.db.new_product(name, 2)
            self.db.new_delivery(name, 1)

        self.assertEqual(
            [p["product_name"] for p in self.db.search_freezer_products("ежи")],
            ["Ёжик"],
        )
        self.assertEqual(
            [p["name"] for p in self.db.search_products("ФИЛ")], ["Филадельфия"]
        )

    def test_get_by_id(self):
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 4)
        product = self.db.get_freezer_product("Медовик")
        self.assertEqual(self.db.get_freezer_product_by_id(product["id"]), product)
        self.assertIsNone(self.db.get_freezer_product_by_id(999))


class FridgeTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)

    def test_move_to_fridge_returns_batch(self):
        batch = self.db.move_to_fridge("Медовик", 2, user_id=10)
        self.assertEqual(batch["product_name"], "Медовик")
        self.assertEqual(batch["quantity"], 2)
        self.assertEqual(self.db.get_fridge_batch(batch["id"]), batch)
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 3)

        self.db.move_to_fridge("Медовик", 3)
        self.assertIsNone(self.db.get_freezer_product("Медовик"))
        with self.assertRaises(ValueError):
            self.db.move_to_fridge("Медовик", 1)

    def test_write_off_and_sale_texts(self):
        batch = self.db.move_to_fridge("Медовик", 3)

        text = self.db.clear_expired_product(
            id=batch["id"], quantity=1, operation_type="write_off",
            user_id=10, reason="Повреждено",
        )
        self.assertIn("Списано", text)
        self.assertIn("Причина: Повреждено", text)
        self.assertNotIn("write_off", text)

        text = self.db.clear_expired_product(
            id=batch["id"], quantity=2, operation_type="sale", user_id=10
        )
        self.assertIn("Продано", text)
        self.assertIn("Партия закрыта полностью", text)
        self.assertIsNone(self.db.get_fridge_batch(batch["id"]))

        self.assertFalse(self.db.clear_expired_product(
            id=batch["id"], quantity=1, operation_type="sale"
        ))

    def test_write_off_without_reason_keeps_reason_empty(self):
        batch = self.db.move_to_fridge("Медовик", 1)
        self.db.clear_expired_product(id=batch["id"], quantity=1, operation_type="write_off")
        _, records = self.db.write_off_history()
        self.assertIsNone(records[0]["reason"])

    def test_search_batches(self):
        self.db.move_to_fridge("Медовик", 1)
        self.assertEqual(len(self.db.search_fridge_batches("МЕД")), 1)
        self.assertEqual(self.db.search_fridge_batches("лосось"), [])


class ProductsTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_product("Калифорния", 1)

    def test_products_list(self):
        page_count, products = self.db.products_list(page=1, limit=5)
        self.assertEqual(page_count, 1)
        self.assertEqual([p["name"] for p in products], ["Калифорния", "Медовик"])
        product = self.db.get_product("Медовик")
        self.assertEqual(self.db.get_product_by_id(product["id"]), product)

    def test_edit_storage_time_keeps_freezer_time(self):
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE products SET freezer_storage_time = 90 WHERE name = 'Медовик'")

        self.db.edit_product("Медовик", 5)
        product = self.db.get_product("Медовик")
        self.assertEqual(product["fridge_storage_time"], 5)
        self.assertEqual(product["freezer_storage_time"], 90)

    def test_rename_moves_stock(self):
        self.db.new_delivery("Медовик", 5)
        batch = self.db.move_to_fridge("Медовик", 2)

        self.db.edit_product("Медовик", 3, new_name="Медовик классический")

        self.assertIsNone(self.db.get_product("Медовик"))
        self.assertEqual(self.db.get_freezer_product("Медовик классический")["quantity"], 3)
        self.assertEqual(
            self.db.get_fridge_batch(batch["id"])["product_name"], "Медовик классический"
        )
        self.db.move_to_fridge("Медовик классический", 1)

    def test_rename_to_existing_name_fails(self):
        with self.assertRaises(ValueError):
            self.db.edit_product("Медовик", 3, new_name="Калифорния")
        self.assertIsNotNone(self.db.get_product("Медовик"))
        with self.assertRaises(ValueError):
            self.db.edit_product("Нет такого", 3)

    def test_delete(self):
        self.db.new_delivery("Медовик", 1)
        with self.assertRaises(ValueError):
            self.db.delete_product("Медовик")  # остаток в морозильнике

        self.db.delete_product("Калифорния")
        self.assertIsNone(self.db.get_product("Калифорния"))
        with self.assertRaises(ValueError):
            self.db.delete_product("Калифорния")


class UsersTest(TempDatabaseTestCase):
    def test_users(self):
        self.assertFalse(self.db.has_login_users())
        ivan = self.db.add_user("ivan", "Иван", "hash")
        anna = self.db.add_user("anna", "Анна", "hash", "admin")
        with self.assertRaises(ValueError):
            self.db.add_user("IVAN", "Ещё Иван", "hash")  # логин без учёта регистра
        with self.assertRaises(ValueError):
            self.db.add_user("petr", "Пётр", "hash", "boss")
        self.assertTrue(self.db.has_login_users())

        self.assertEqual(
            [user["full_name"] for user in self.db.users_list()], ["Анна", "Иван"]
        )
        self.assertEqual(self.db.get_user_by_username("Ivan")["id"], ivan)
        self.db.set_user_active(ivan, False)
        self.assertFalse(self.db.get_user(ivan)["is_active"])
        self.assertEqual(self.db.active_users_ids(), [anna])

        self.db.set_user_role(ivan, "admin")
        self.assertEqual(self.db.get_user(ivan)["role"], "admin")
        with self.assertRaises(ValueError):
            self.db.set_user_role(99, "admin")
        with self.assertRaises(ValueError):
            self.db.set_user_username(ivan, "ANNA")

        self.db.set_user_password(ivan, "new-hash")
        self.db.touch_last_login(ivan)
        user = self.db.get_user(ivan)
        self.assertEqual(user["password_hash"], "new-hash")
        self.assertIsNotNone(user["last_login"])


class HistoryAndNotificationsTest(TempDatabaseTestCase):
    def test_write_off_history_newest_first(self):
        self.assertEqual(self.db.write_off_history(), (0, None))
        ivan = self.db.add_user("ivan", "Иван", "hash")
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 20)
        batch = self.db.move_to_fridge("Медовик", 20)
        for reason in ("Первая", "Вторая", "Третья"):
            self.db.clear_expired_product(
                id=batch["id"], quantity=1, user_id=ivan, reason=reason
            )
        self.db.clear_expired_product(id=batch["id"], quantity=1, operation_type="sale")

        page_count, records = self.db.write_off_history(page=1, limit=2)
        self.assertEqual(page_count, 2)
        self.assertEqual([r["reason"] for r in records], ["Третья", "Вторая"])
        self.assertEqual(records[0]["full_name"], "Иван")
        self.assertEqual(self.db.write_off_history(page=3, limit=2), (None, None))

    def test_operations_log_filters(self):
        ivan = self.db.add_user("ivan", "Иван", "hash")
        self.db.new_product("Ёжик", 3)
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Ёжик", 5, user_id=ivan)
        self.db.new_delivery("Медовик", 5)
        batch = self.db.move_to_fridge("Ёжик", 2, user_id=ivan)
        self.db.clear_expired_product(
            id=batch["id"], quantity=1, user_id=ivan, reason="Повреждено"
        )

        self.assertEqual(self.db.operations_log()[0], 4)
        self.assertEqual(self.db.operations_log(user_id=ivan)[0], 3)
        total, rows = self.db.operations_log(operation_type="write_off")
        self.assertEqual((total, rows[0]["full_name"]), (1, "Иван"))
        # Поиск без учёта регистра и «ё»: встроенный LIKE так не умеет.
        self.assertEqual(self.db.operations_log(query="ЕЖИК")[0], 3)
        self.assertEqual(self.db.operations_log(query="поврежд")[0], 1)
        today = rows[0]["created_at"][:10]
        self.assertEqual(self.db.operations_log(date_from=today, date_to=today)[0], 4)
        self.assertEqual(self.db.operations_log(date_to="2000-01-01")[0], 0)
        total, rows = self.db.operations_log(page=2, limit=3)
        self.assertEqual((total, len(rows)), (4, 1))

    def test_mark_daily_notification(self):
        self.assertTrue(self.db.mark_daily_notification(10, "2026-10-01"))
        self.assertFalse(self.db.mark_daily_notification(10, "2026-10-01"))
        self.assertTrue(self.db.mark_daily_notification(11, "2026-10-01"))
        self.assertTrue(self.db.mark_daily_notification(10, "2026-10-02"))

    def test_errors_and_audit(self):
        self.db.log_error("ValueError", "Traceback…")
        total, errors = self.db.errors_list()
        self.assertEqual(total, 1)
        self.assertIsNotNone(errors[0]["created_at"])

        self.db.log_action("login", user_id=1, username="admin", ip="127.0.0.1")
        self.db.log_action("db_update", "products #1: name: А → Б", 1, "admin")
        self.assertEqual(self.db.audit_list()[0], 2)
        self.assertEqual(self.db.audit_list(action="login")[0], 1)
        self.assertEqual(self.db.audit_list(query="PRODUCTS")[1][0]["action"], "db_update")


class ProductCatalogTest(TempDatabaseTestCase):
    def test_new_product_with_all_fields_and_update(self):
        self.db.new_product("Медовик", 3, 90, "Десерты")
        self.db.new_delivery("Медовик", 4)
        self.db.move_to_fridge("Медовик", 1)
        product = self.db.get_product("Медовик")
        self.assertEqual(
            (product["freezer_storage_time"], product["category"]), (90, "Десерты")
        )

        self.db.update_product("Медовик", "Медовик классический", 2, None, None)
        product = self.db.get_product("Медовик классический")
        self.assertEqual(
            (product["fridge_storage_time"], product["freezer_storage_time"],
             product["category"]),
            (2, None, None),
        )
        # Остатки переименованы вместе с товаром.
        self.assertEqual(self.db.freezer_items()[0]["product_name"], "Медовик классический")
        self.assertEqual(self.db.fridge_batches_list()[0]["product_name"], "Медовик классический")
        self.assertEqual(self.db.catalog()[0]["freezer_quantity"], 3)

        self.db.new_product("Чизкейк", 2)
        with self.assertRaises(ValueError):
            self.db.update_product("Чизкейк", "Медовик классический", 2, None, None)
        with self.assertRaises(ValueError):
            self.db.update_product("Нет такого", "Нет", 2, None, None)


class TableEditorTest(TempDatabaseTestCase):
    def test_tables_and_rows(self):
        self.assertIn("products", self.db.table_names())
        self.assertNotIn("sqlite_sequence", self.db.table_names())
        with self.assertRaises(KeyError):
            self.db.table_columns("products; DROP TABLE users")

        rowid = self.db.insert_row(
            "products", {"name": "Медовик", "fridge_storage_time": 3}
        )
        self.assertEqual(self.db.table_row("products", rowid)["name"], "Медовик")
        self.db.update_row("products", rowid, {"category": "Десерты"})
        total, rows = self.db.table_rows("products", query="десерт")
        self.assertEqual((total, rows[0]["__rowid"]), (1, rowid))

        with self.assertRaises(ValueError):  # CHECK (quantity > 0)
            self.db.insert_row("freezer", {"product_name": "Медовик", "quantity": 0})
        with self.assertRaises(ValueError):
            self.db.update_row("products", rowid, {"no_such_column": 1})
        with self.assertRaises(ValueError):
            self.db.insert_row("audit_log", {"action": "login", "created_at": "x"})

        self.db.delete_row("products", rowid)
        self.assertIsNone(self.db.table_row("products", rowid))
        with self.assertRaises(ValueError):
            self.db.delete_row("products", rowid)

    def test_sorting(self):
        for name in ("Б", "А", "В"):
            self.db.new_product(name, 1)
        _, rows = self.db.table_rows("products", sort="name", descending=True)
        self.assertEqual([row["name"] for row in rows], ["В", "Б", "А"])
        _, rows = self.db.table_rows("products", sort="no_such_column")
        self.assertEqual([row["name"] for row in rows], ["Б", "А", "В"])


class MigrationTest(TempDatabaseTestCase):
    """База, созданная Telegram-ботом, открывается сайтом без потерь."""

    BOT_SCHEMA = """
    CREATE TABLE users (
        telegram_id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'employee')),
        is_active BOOLEAN NOT NULL DEFAULT FALSE
    );
    CREATE TABLE operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_type TEXT NOT NULL,
        product_name TEXT NOT NULL,
        batch_id INTEGER,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        reason TEXT,
        created_at TEXT NOT NULL,
        created_by INTEGER NOT NULL,
        FOREIGN KEY (created_by) REFERENCES users(telegram_id)
    );
    CREATE TABLE errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_type TEXT NOT NULL,
        error_message TEXT NOT NULL
    );
    CREATE TABLE daily_notifications (
        telegram_id INTEGER PRIMARY KEY,
        last_date TEXT NOT NULL
    );
    INSERT INTO users VALUES (123456789, 'Иван', 'employee', TRUE);
    INSERT INTO operations (
        operation_type, product_name, quantity, reason, created_at, created_by
    ) VALUES ('write_off', 'Медовик', 1, 'Просрочено', '2026-10-01 10:00', 123456789);
    INSERT INTO errors (error_type, error_message) VALUES ('ValueError', 'старая');
    INSERT INTO daily_notifications VALUES (123456789, '2026-10-01');
    """

    def test_bot_database(self):
        path = str(self.temp_path / "bot.db")
        connection = sqlite3.connect(path)
        connection.executescript(self.BOT_SCHEMA)
        connection.close()

        db = Database(path)

        user = db.get_user(123456789)
        self.assertEqual(
            (user["username"], user["password_hash"], user["full_name"]),
            ("tg123456789", None, "Иван"),
        )
        _, operations = db.operations_log()
        self.assertEqual(operations[0]["full_name"], "Иван")
        self.assertEqual(db.errors_list()[1][0]["error_message"], "старая")
        self.assertFalse(db.mark_daily_notification(123456789, "2026-10-01"))
        self.assertFalse(db.has_login_users())
        self.assertIn("audit_log", db.table_names())
        # Повторное открытие ничего не ломает.
        Database(path).add_user("admin", "Админ", "hash", "admin")


class StockTablesTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        for name, days in (("Филадельфия", 2), ("Медовик", 3), ("Калифорния", 1)):
            self.db.new_product(name, days)
            self.db.new_delivery(name, 10)
        self.db.move_to_fridge("Медовик", 2)
        self.db.move_to_fridge("Филадельфия", 1)

    def ids(self):
        products = {p["name"]: p["id"] for p in self.db.products_list(1, 100)[1]}
        freezer = {p["product_name"]: p["id"] for p in self.db.freezer_products_list(1, 100)[1]}
        return products, freezer

    def test_replace_with_same_data_changes_nothing(self):
        before, ids_before = self.db.stock_tables(), self.ids()
        self.db.replace_stock_tables(**self.db.stock_tables())
        self.assertEqual(self.db.stock_tables(), before)
        self.assertEqual(self.ids(), ids_before)

    def test_replace_keeps_ids_and_numbers_new_rows(self):
        (product_ids, _), tables = self.ids(), self.db.stock_tables()
        tables["products"] = [p for p in tables["products"] if p["name"] != "Калифорния"]
        tables["freezer"] = [f for f in tables["freezer"] if f["product_name"] != "Калифорния"]
        tables["products"].append({"name": "Лосось", "fridge_storage_time": 3})
        tables["fridge"].append({
            "id": None, "product_name": "Лосось", "quantity": 4,
            "date_added": "2026-10-01", "expiration_date": "2026-10-04",
        })
        old_batch_ids = [batch["id"] for batch in tables["fridge"] if batch["id"]]

        self.db.replace_stock_tables(**tables)

        new_product_ids, _ = self.ids()
        self.assertEqual(new_product_ids["Медовик"], product_ids["Медовик"])
        self.assertGreater(new_product_ids["Лосось"], max(product_ids.values()))
        batch_ids = [batch["id"] for batch in self.db.fridge_batches_list()]
        self.assertTrue(set(old_batch_ids) <= set(batch_ids))
        self.assertGreater(max(batch_ids), max(old_batch_ids))

    def test_backup(self):
        before = self.db.stock_tables()
        backup_path = str(self.temp_path / "backups" / "copy.db")
        self.db.backup(backup_path)
        self.db.replace_stock_tables(products=[], freezer=[], fridge=[])
        self.assertEqual(Database(backup_path).stock_tables(), before)

    def test_restore(self):
        before = self.db.stock_tables()
        backup_path = str(self.temp_path / "backups" / "copy.db")
        self.db.backup(backup_path)
        self.db.replace_stock_tables(products=[], freezer=[], fridge=[])

        self.db.restore(backup_path)
        self.assertEqual(self.db.stock_tables(), before)

        not_a_database = self.temp_path / "broken.db"
        not_a_database.write_text("не база данных")
        with self.assertRaises(ValueError):
            self.db.restore(str(not_a_database))
        self.assertEqual(self.db.stock_tables(), before)


if __name__ == "__main__":
    unittest.main()
