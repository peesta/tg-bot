"""Методы storage/db.py, которые вызывает бот."""
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
        self.db.add_user(10, "Иван")
        self.db.add_user(11, "Анна", "admin")
        with self.assertRaises(ValueError):
            self.db.add_user(10, "Ещё Иван")
        with self.assertRaises(ValueError):
            self.db.add_user(12, "Пётр", "boss")

        self.assertEqual(
            [user["full_name"] for user in self.db.users_list()], ["Анна", "Иван"]
        )
        self.db.set_user_active(10, False)
        self.assertFalse(self.db.get_user(10)["is_active"])
        self.assertEqual(self.db.active_users_ids(), [11])

        self.db.set_user_role(10, "admin")
        self.assertEqual(self.db.get_user(10)["role"], "admin")
        with self.assertRaises(ValueError):
            self.db.set_user_role(99, "admin")


class HistoryAndNotificationsTest(TempDatabaseTestCase):
    def test_write_off_history_newest_first(self):
        self.assertEqual(self.db.write_off_history(), (0, None))
        self.db.add_user(10, "Иван")
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 20)
        batch = self.db.move_to_fridge("Медовик", 20)
        for reason in ("Первая", "Вторая", "Третья"):
            self.db.clear_expired_product(
                id=batch["id"], quantity=1, user_id=10, reason=reason
            )
        self.db.clear_expired_product(id=batch["id"], quantity=1, operation_type="sale")

        page_count, records = self.db.write_off_history(page=1, limit=2)
        self.assertEqual(page_count, 2)
        self.assertEqual([r["reason"] for r in records], ["Третья", "Вторая"])
        self.assertEqual(records[0]["full_name"], "Иван")
        self.assertEqual(self.db.write_off_history(page=3, limit=2), (None, None))

    def test_mark_daily_notification(self):
        self.assertTrue(self.db.mark_daily_notification(10, "2026-10-01"))
        self.assertFalse(self.db.mark_daily_notification(10, "2026-10-01"))
        self.assertTrue(self.db.mark_daily_notification(11, "2026-10-01"))
        self.assertTrue(self.db.mark_daily_notification(10, "2026-10-02"))


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


if __name__ == "__main__":
    unittest.main()
