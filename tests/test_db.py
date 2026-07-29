import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from storage.db import Database


class DatabaseOperationsTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "database.db"
        self.database = Database(str(database_path))

        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products (
                    name,
                    fridge_storage_time,
                    freezer_storage_time,
                    category
                )
                VALUES ('Лосось', 3, 30, 'Рыба')
                """
            )
            cursor.executemany(
                """
                INSERT INTO users (telegram_id, full_name, role, is_active)
                VALUES (?, ?, 'employee', TRUE)
                """,
                ((101, "Первый сотрудник"), (202, "Второй сотрудник")),
            )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_delivery_and_defrost_are_logged_with_user_id(self):
        self.database.new_delivery("Лосось", 5, user_id=101)
        self.database.move_to_fridge("Лосось", 5, user_id=202)

        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_type, product_name, batch_id, quantity, created_by
                FROM operations
                ORDER BY id
                """
            )
            operations = [tuple(row) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT quantity FROM freezer WHERE product_name = 'Лосось'"
            )
            freezer_row = cursor.fetchone()

        self.assertEqual(
            operations,
            [
                ("delivery", "Лосось", None, 5, 101),
                ("defrost", "Лосось", 1, 5, 202),
            ],
        )
        self.assertIsNone(freezer_row)

    def test_repeated_deliveries_accumulate_freezer_stock(self):
        self.database.new_delivery("Лосось", 2, user_id=101)
        self.database.new_delivery("Лосось", 3, user_id=202)

        with self.database.cursor() as cursor:
            cursor.execute(
                "SELECT quantity FROM freezer WHERE product_name = 'Лосось'"
            )
            freezer_quantity = cursor.fetchone()["quantity"]
            cursor.execute(
                """
                SELECT quantity, created_by
                FROM operations
                WHERE operation_type = 'delivery'
                ORDER BY id
                """
            )
            deliveries = [tuple(row) for row in cursor.fetchall()]

        self.assertEqual(freezer_quantity, 5)
        self.assertEqual(deliveries, [(2, 101), (3, 202)])

    def test_partial_sale_is_logged_and_reduces_batch(self):
        self.database.new_delivery("Лосось", 5, user_id=101)
        self.database.move_to_fridge("Лосось", 5, user_id=101)

        self.database.clear_expired_product(
            id=1,
            quantity=2,
            operation_type="sale",
            user_id=202,
        )

        with self.database.cursor() as cursor:
            cursor.execute("SELECT quantity FROM fridge WHERE id = 1")
            remaining_quantity = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT operation_type, product_name, batch_id, quantity,
                       reason, created_by
                FROM operations
                WHERE operation_type = 'sale'
                """
            )
            operation = tuple(cursor.fetchone())

        self.assertEqual(remaining_quantity, 3)
        self.assertEqual(
            operation,
            ("sale", "Лосось", 1, 2, None, 202),
        )

    def test_call_without_arguments_writes_off_every_expired_batch(self):
        today = datetime.now()
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        two_days_ago = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        today_text = today.strftime("%Y-%m-%d")

        with self.database.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO fridge (
                    product_name,
                    quantity,
                    date_added,
                    expiration_date
                )
                VALUES ('Лосось', ?, ?, ?)
                """,
                (
                    (2, two_days_ago, two_days_ago),
                    (3, yesterday, yesterday),
                    (4, today_text, today_text),
                ),
            )

        result = self.database.clear_expired_product()

        with self.database.cursor() as cursor:
            cursor.execute(
                "SELECT quantity, expiration_date FROM fridge ORDER BY id"
            )
            active_batches = [tuple(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT operation_type, quantity, reason, created_by
                FROM operations
                ORDER BY id
                """
            )
            operations = [tuple(row) for row in cursor.fetchall()]

        self.assertIn("Списано просроченных партий: 2", result)
        self.assertEqual(active_batches, [(4, today_text)])
        self.assertEqual(
            operations,
            [
                ("write_off", 2, "expired", 0),
                ("write_off", 3, "expired", 0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
