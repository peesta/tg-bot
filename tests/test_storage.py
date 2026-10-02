"""Учётные записи, запросы для сайта и редактор таблиц."""
import unittest

from storage import queries, table_editor
from storage.accounts import Accounts, check_password, hash_password
from tests.helpers import TempDatabaseTestCase, set_expiration


ADMIN = {"id": 1, "role": "admin"}


class AccountsTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.accounts = Accounts(self.db)

    def test_password_hash(self):
        password_hash = hash_password("secret")
        self.assertNotIn("secret", password_hash)
        self.assertTrue(check_password(password_hash, "secret"))
        self.assertFalse(check_password(password_hash, "Secret"))
        self.assertFalse(check_password(None, "secret"))
        self.assertFalse(check_password("мусор", "secret"))

    def test_default_accounts_only_once(self):
        self.assertTrue(self.accounts.create_defaults())
        admin = self.accounts.get_by_username("ADMIN")  # без учёта регистра
        employee = self.accounts.get_by_username("employee")
        self.assertEqual((admin["id"], admin["role"]), (1, "admin"))
        self.assertEqual((employee["id"], employee["role"]), (2, "employee"))
        self.assertTrue(check_password(admin["password_hash"], "admin"))
        self.assertTrue(check_password(employee["password_hash"], "employee"))
        self.assertFalse(self.accounts.create_defaults())

    def test_create_user_logs_and_logs_in(self):
        user_id = self.accounts.create_user("Анна", "anna", "pass1", "employee", created_by=1)
        user = self.accounts.get(user_id)
        self.assertEqual((user["full_name"], user["username"], user["is_active"]), ("Анна", "anna", True))
        with self.assertRaises(ValueError):
            self.accounts.create_user("Другая Анна", "ANNA", "pass2", "employee")
        with self.db.cursor() as cursor:
            cursor.execute("SELECT action, user_id FROM change_log ORDER BY id")
            self.assertEqual(
                [tuple(row) for row in cursor.fetchall()],
                [("user_added", 1), ("account_changed", 1)],
            )

    def test_bot_user_without_login(self):
        # Сотрудник из Telegram-бота: есть в users, логина нет.
        self.db.add_user(123456789, "Иван")
        user = self.accounts.get(123456789)
        self.assertIsNone(user["username"])
        with self.assertRaises(ValueError):
            self.accounts.set_login(123456789, "ivan")  # без пароля нельзя
        self.accounts.set_login(123456789, "ivan", "pass1", changed_by=1)
        self.assertTrue(check_password(self.accounts.get_by_username("ivan")["password_hash"], "pass1"))
        # Следующий номер — после самого большого.
        self.assertEqual(self.accounts.create_user("Анна", "anna", "pass1", "employee"), 123456790)

    def test_set_password_and_username(self):
        user_id = self.accounts.create_user("Анна", "anna", "pass1", "employee")
        self.accounts.set_password(user_id, "pass2", changed_by=1)
        self.accounts.set_login(user_id, "anna.p", changed_by=1)
        user = self.accounts.get_by_username("anna.p")
        self.assertTrue(check_password(user["password_hash"], "pass2"))
        with self.db.cursor() as cursor:
            cursor.execute("SELECT details FROM change_log WHERE action = 'account_changed' ORDER BY id")
            details = [row["details"] for row in cursor.fetchall()]
        self.assertIn("новый пароль", details[-2])
        self.assertIn("«anna» → «anna.p»", details[-1])
        self.assertNotIn("pass2", " ".join(details))


class QueriesTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.add_user(10, "Иван")
        self.db.new_product("Ёжик", 3)
        self.db.new_product("Медовик", 2)
        self.db.new_delivery("Ёжик", 5, user_id=10)
        self.db.new_delivery("Медовик", 4)
        self.batch = self.db.move_to_fridge("Ёжик", 2, user_id=10)
        self.db.clear_expired_product(id=self.batch["id"], quantity=1, user_id=10, reason="Повреждено")

    def test_catalog_and_freezer(self):
        catalog = queries.catalog(self.db)
        self.assertEqual([(p["name"], p["freezer_quantity"]) for p in catalog], [("Ёжик", 3), ("Медовик", 4)])
        freezer = queries.freezer_items(self.db)
        self.assertEqual(freezer[0]["fridge_storage_time"], 3)

    def test_operations_log_filters(self):
        self.assertEqual(queries.operations_log(self.db)[0], 4)
        self.assertEqual(queries.operations_log(self.db, user_id=10)[0], 3)
        total, rows = queries.operations_log(self.db, operation_type="write_off")
        self.assertEqual((total, rows[0]["full_name"]), (1, "Иван"))
        # Поиск без учёта регистра кириллицы и «ё»: встроенный LIKE так не умеет.
        self.assertEqual(queries.operations_log(self.db, query="ЕЖИК")[0], 3)
        self.assertEqual(queries.operations_log(self.db, query="поврежд")[0], 1)
        today = queries.today()
        self.assertEqual(queries.operations_log(self.db, date_from=today, date_to=today)[0], 4)
        self.assertEqual(queries.operations_log(self.db, date_to="2000-01-01")[0], 0)
        total, rows = queries.operations_log(self.db, page=2, limit=3)
        self.assertEqual((total, len(rows)), (4, 1))

    def test_stats(self):
        set_expiration(self.db, self.batch["id"], -1)
        self.db.log_error("X", "y")
        stats = queries.stats(self.db)
        self.assertEqual(stats["products"], 2)
        self.assertEqual(stats["freezer_quantity"], 7)
        self.assertEqual(stats["expired"], 1)
        self.assertEqual(stats["operations_today"], 4)
        self.assertEqual(stats["errors_today"], 1)
        self.assertNotIn("active_users", stats)

    def test_change_log_search(self):
        self.db.log_change("backup_created", "Копия для ЁЖИКА", user_id=10)
        total, rows = queries.change_log(self.db, query="копия для ежика")
        self.assertEqual((total, rows[0]["full_name"]), (1, "Иван"))
        # «иван» — и в подробностях добавления сотрудника, и в имени автора копии.
        self.assertEqual(queries.change_log(self.db, query="иван")[0], 2)


class TableEditorTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        Accounts(self.db).create_defaults()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)
        self.batch = self.db.move_to_fridge("Медовик", 2)
        self.fridge = table_editor.TABLES["fridge"]
        self.users = table_editor.TABLES["users"]

    def last_change(self):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")
            return dict(cursor.fetchone())

    def test_russian_labels(self):
        for table in table_editor.TABLES.values():
            for column in table.columns:
                self.assertRegex(column.label, "[А-Яа-я№]", f"{table.name}.{column.name}")
        names = [table["name"] for table in table_editor.list_tables(self.db)]
        self.assertNotIn("accounts", names)  # пароли — только в «Сотрудниках»
        self.assertNotIn("change_log", names)  # журнал не правится
        with self.assertRaises(KeyError):
            table_editor.table_spec("accounts")

    def test_update_logs_in_russian(self):
        row = table_editor.update_row(
            self.db, self.fridge, self.batch["id"],
            {"quantity": 7, "expiration_date": "2026-12-31"}, ADMIN,
        )
        self.assertEqual((row["quantity"], row["expiration_date"]), (7, "2026-12-31"))
        change = self.last_change()
        self.assertEqual((change["action"], change["user_id"], change["table_name"]), ("row_changed", 1, "fridge"))
        self.assertIn("Холодильник, партия № 1 «Медовик»", change["details"])
        self.assertIn("Количество, шт.: 2 → 7", change["details"])

    def test_validation(self):
        cases = [
            ({"quantity": "abc"}, "нужно целое число"),
            ({"quantity": 0}, "не меньше 1"),
            ({"quantity": True}, "нужно целое число"),
            ({"expiration_date": "31.12.2026"}, "выберите дату"),
            ({"expiration_date": "2000-01-01"}, "раньше даты разморозки"),
            ({"product_name": "Пицца"}, "нет в справочнике"),
            ({"product_name": ""}, "Заполните «Товар»"),
            ({"id": 5, "no_such": 1}, "Нет таких полей"),
        ]
        for values, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                table_editor.update_row(self.db, self.fridge, self.batch["id"], values, ADMIN)
        with self.assertRaisesRegex(ValueError, "Заполните"):
            table_editor.insert_row(self.db, self.fridge, {"product_name": "Медовик"}, ADMIN)

    def test_insert_and_delete(self):
        rowid = table_editor.insert_row(self.db, self.fridge, {
            "product_name": "Медовик", "quantity": 3,
            "date_added": "2026-10-01", "expiration_date": "2026-10-04",
        }, ADMIN)
        self.assertEqual(self.db.get_fridge_batch(rowid)["quantity"], 3)
        self.assertEqual(self.last_change()["action"], "row_added")
        table_editor.delete_row(self.db, self.fridge, rowid, ADMIN)
        self.assertIsNone(self.db.get_fridge_batch(rowid))
        self.assertIn("удалена партия", self.last_change()["details"])

    def test_unique_and_check_errors_are_readable(self):
        products = table_editor.TABLES["products"]
        self.db.new_product("Чизкейк", 2)
        with self.assertRaisesRegex(ValueError, "уже есть в таблице"):
            table_editor.update_row(self.db, products, self.db.get_product("Чизкейк")["id"], {"name": "Медовик"}, ADMIN)

    def test_admin_cannot_remove_own_rights(self):
        with self.assertRaisesRegex(ValueError, "Нельзя лишить себя прав"):
            table_editor.update_row(self.db, self.users, 1, {"role": "employee"}, ADMIN)
        with self.assertRaisesRegex(ValueError, "Нельзя отключить доступ"):
            table_editor.update_row(self.db, self.users, 1, {"is_active": False}, ADMIN)
        with self.assertRaisesRegex(ValueError, "Нельзя удалить самого себя"):
            table_editor.delete_row(self.db, self.users, 1, ADMIN)
        # Имя себе поменять можно, другому — и права тоже.
        table_editor.update_row(self.db, self.users, 1, {"full_name": "Главный"}, ADMIN)
        table_editor.update_row(self.db, self.users, 2, {"is_active": False}, ADMIN)
        self.assertFalse(self.db.get_user(2)["is_active"])
        with self.assertRaisesRegex(ValueError, "строки добавляются в своём разделе"):
            table_editor.insert_row(self.db, self.users, {"full_name": "X", "role": "admin"}, ADMIN)

    def test_deleting_user_removes_login(self):
        accounts = Accounts(self.db)
        table_editor.delete_row(self.db, self.users, 2, ADMIN)
        self.assertIsNone(accounts.get_by_username("employee"))
        accounts.create_user("Новый", "employee", "pass1", "employee")  # логин свободен

    def test_rows_search_and_sort(self):
        self.db.new_product("Ёжик", 1)
        products = table_editor.TABLES["products"]
        total, rows = table_editor.rows(self.db, products, query="ЕЖ")
        self.assertEqual((total, rows[0]["name"]), (1, "Ёжик"))
        _, rows = table_editor.rows(self.db, products, sort="name", descending=True)
        self.assertEqual([row["name"] for row in rows], ["Медовик", "Ёжик"])
        operations = table_editor.TABLES["operations"]
        _, rows = table_editor.rows(self.db, operations)  # журнал — новые сверху
        self.assertEqual(rows[0]["operation_type"], "defrost")

    def test_options(self):
        options = table_editor.options(self.db, table_editor.TABLES["operations"])
        self.assertIn({"value": "sale", "label": "Продажа"}, options["operation_type"])
        self.assertEqual(options["created_by"][0], {"value": 0, "label": "Система"})
        self.assertIn({"value": "Медовик", "label": "Медовик"}, table_editor.options(self.db, self.fridge)["product_name"])


if __name__ == "__main__":
    unittest.main()
