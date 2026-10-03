"""API сайта: вход, роли, разделы сотрудника и администратора, журналы."""
import unittest
from unittest import mock

from storage.accounts import check_password
from storage.db import Database
from tests.helpers import ApiTestCase, set_expiration


ADMIN_URLS = (
    "/api/admin/products", "/api/admin/users", "/api/admin/tables",
    "/api/admin/tables/fridge", "/api/admin/logs/operations",
    "/api/admin/logs/changes", "/api/admin/logs/errors",
    "/api/admin/logs/server", "/api/admin/google", "/api/admin/backups",
)
STAFF_URLS = (
    "/api/dashboard", "/api/expiring", "/api/freezer", "/api/catalog",
    "/api/batches", "/api/stock", "/api/history", "/api/auth/me",
)


class AuthTest(ApiTestCase):
    def test_default_accounts(self):
        self.assertEqual(self.login("admin").json()["role"], "admin")
        self.assertEqual(self.login("employee", client=self.client_for()).json()["role"], "employee")
        self.assertNotIn("password_hash", self.client.get("/api/auth/me").text)

    def test_requires_login(self):
        for url in STAFF_URLS + ADMIN_URLS:
            self.assertEqual(self.client.get(url).status_code, 401, url)

    def test_wrong_password_and_rate_limit(self):
        for _ in range(5):
            response = self.client.post("/api/auth/login", json={"username": "admin", "password": "x"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "Неверный логин или пароль")
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 429)

    def test_login_is_case_insensitive_and_logout(self):
        self.login("ADMIN", "admin")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_changes_require_header(self):
        response = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin"},
            headers={"X-Requested-With": ""},
        )
        self.assertEqual(response.status_code, 403)

    def test_disabled_user_is_logged_out(self):
        self.login("employee")
        self.db.set_user_active(self.EMPLOYEE_ID, False)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        response = self.client.post("/api/auth/login", json={"username": "employee", "password": "employee"})
        self.assertEqual(response.status_code, 403)

    def test_change_own_password(self):
        self.login("employee")
        other = self.client_for()
        self.login("employee", client=other)

        response = self.client.post("/api/auth/password", json={"current_password": "x", "new_password": "pass1"})
        self.assertEqual(response.json()["detail"], "Текущий пароль указан неверно")
        response = self.client.post("/api/auth/password", json={"current_password": "employee", "new_password": "pass1"})
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)  # эта сессия живёт
        self.assertEqual(other.get("/api/auth/me").status_code, 401)  # другие сброшены
        self.assertTrue(check_password(self.accounts.get(self.EMPLOYEE_ID)["password_hash"], "pass1"))


class RolesTest(ApiTestCase):
    def test_employee_has_no_admin_api(self):
        self.login("employee")
        for url in STAFF_URLS:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for url in ADMIN_URLS:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        response = self.client.patch("/api/admin/tables/users/rows/2", json={"values": {"role": "admin"}})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.get_user(self.EMPLOYEE_ID)["role"], "employee")
        # Попытки зайти в админку записываются в ошибки.
        self.assertTrue(any(error["error_type"] == "HTTP 403" for error in self.errors()))

    def test_dashboards_differ(self):
        self.login("employee")
        employee = self.client.get("/api/dashboard").json()
        self.assertIn("my_operations", employee)
        self.assertNotIn("stats", employee)

        self.login("admin")
        admin = self.client.get("/api/dashboard").json()
        self.assertIn("operations", admin)
        self.assertNotIn("active_users", admin["stats"])  # «пользователей с доступом» нет


class StaffTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_product("Филадельфия", 2)
        self.login("employee")

    def make_batch(self, name="Медовик", quantity=5, days=None):
        self.db.new_delivery(name, quantity)
        batch = self.db.move_to_fridge(name, quantity)
        if days is not None:
            set_expiration(self.db, batch["id"], days)
        return batch["id"]

    def test_delivery_and_defrost(self):
        product_id = self.db.get_product("Медовик")["id"]
        response = self.client.post("/api/delivery", json={"product_id": product_id, "quantity": 5})
        self.assertEqual(response.json()["in_freezer"], 5)

        freezer = self.client.get("/api/freezer").json()
        self.assertEqual(freezer[0]["product_name"], "Медовик")
        self.assertRegex(freezer[0]["expires"], r"^\d{4}-\d{2}-\d{2}$")  # формат даты — на клиенте

        response = self.client.post("/api/defrost", json={"product_id": freezer[0]["id"], "quantity": 2})
        batch = response.json()
        self.assertEqual(batch["quantity"], 2)
        self.assertRegex(batch["expiration_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 3)

        with self.db.cursor() as cursor:
            cursor.execute("SELECT operation_type, created_by FROM operations")
            self.assertEqual(
                [tuple(row) for row in cursor.fetchall()],
                [("delivery", self.EMPLOYEE_ID), ("defrost", self.EMPLOYEE_ID)],
            )

    def test_delivery_to_fridge(self):
        product = next(item for item in self.client.get("/api/catalog").json() if item["name"] == "Медовик")
        self.assertRegex(product["expires"], r"^\d{4}-\d{2}-\d{2}$")  # годен до, если сразу в холодильник
        self.assertEqual(product["fridge_quantity"], 0)

        response = self.client.post("/api/delivery", json={
            "product_id": product["id"], "quantity": 3, "destination": "fridge",
        })
        result = response.json()
        self.assertEqual((result["destination"], result["quantity"]), ("fridge", 3))
        self.assertEqual(result["expiration_date"], product["expires"])

        self.assertIsNone(self.db.get_freezer_product("Медовик"))  # морозильник не тронут
        batch = self.db.get_fridge_batch(result["batch_id"])
        self.assertEqual((batch["product_name"], batch["quantity"]), ("Медовик", 3))
        self.assertEqual(self.client.get("/api/stock").json()["fresh"][0]["id"], result["batch_id"])
        catalog = self.client.get("/api/catalog").json()
        self.assertEqual(next(item for item in catalog if item["name"] == "Медовик")["fridge_quantity"], 3)

        # В журнале — поставка с номером партии.
        [row] = self.client.get("/api/history", params={"type": "delivery"}).json()["items"]
        self.assertEqual((row["batch_id"], row["created_by"]), (result["batch_id"], self.EMPLOYEE_ID))

        response = self.client.post("/api/delivery", json={
            "product_id": product["id"], "quantity": 1, "destination": "shelf",
        })
        self.assertEqual(response.status_code, 422)

    def test_delivery_to_freezer_by_default(self):
        product_id = self.db.get_product("Медовик")["id"]
        result = self.client.post("/api/delivery", json={"product_id": product_id, "quantity": 2}).json()
        self.assertEqual((result["destination"], result["in_freezer"]), ("freezer", 2))
        self.assertEqual(self.client.get("/api/stock").json()["fresh"], [])
        [row] = self.client.get("/api/history").json()["items"]
        self.assertIsNone(row["batch_id"])

    def test_defrost_more_than_stock_is_logged_error(self):
        self.db.new_delivery("Медовик", 2)
        product_id = self.db.get_freezer_product("Медовик")["id"]
        response = self.client.post("/api/defrost", json={"product_id": product_id, "quantity": 5})
        self.assertEqual(response.status_code, 400)
        self.assertIn("от 1 до 2", response.json()["detail"])
        self.assertIn("от 1 до 2", self.errors()[-1]["error_message"])

    def test_write_off_and_sale(self):
        batch_id = self.make_batch()
        self.assertEqual(self.client.get(f"/api/batches/{batch_id}").json()["reasons"]["staff"], "Для сотрудника")

        response = self.client.post(f"/api/batches/{batch_id}/write-off", json={"reason": "damaged", "quantity": 2})
        self.assertIn("Причина: Повреждено", response.json()["message"])
        response = self.client.post(f"/api/batches/{batch_id}/write-off", json={"reason": "other", "reason_text": " "})
        self.assertEqual(response.json()["detail"], "Напишите причину списания")
        response = self.client.post(f"/api/batches/{batch_id}/sale", json={"quantity": 9})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/batches/{batch_id}/sale", json={"whole": True})
        self.assertIn("Партия закрыта полностью", response.json()["message"])
        self.assertEqual(self.client.get(f"/api/batches/{batch_id}").status_code, 404)

        history = self.client.get("/api/history", params={"type": "write_off"}).json()
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["full_name"], "Сотрудник")
        sales = self.client.get("/api/history", params={"type": "sale"}).json()
        self.assertEqual([row["operation_type"] for row in sales["items"]], ["sale"])
        # Без фильтра — все операции: поставка, разморозка, списание, продажа.
        everything = self.client.get("/api/history").json()
        self.assertEqual(
            [row["operation_type"] for row in everything["items"]],
            ["sale", "write_off", "defrost", "delivery"],
        )
        self.assertEqual(self.client.get("/api/history", params={"type": "nope"}).json()["total"], 4)

    def test_expiring_and_clear_all(self):
        self.make_batch("Медовик", 2, days=0)
        self.make_batch("Филадельфия", 3, days=-1)
        self.make_batch("Медовик", 4, days=2)
        data = self.client.get("/api/expiring").json()
        self.assertEqual((len(data["today"]), len(data["expired"])), (1, 1))
        self.assertEqual(data["expired_totals"], [{"product_name": "Филадельфия", "quantity": 3}])

        response = self.client.post("/api/expiring/clear")
        self.assertIn("Списано просроченных партий: 2", response.json()["message"])
        stock = self.client.get("/api/stock").json()
        self.assertEqual((len(stock["fresh"]), len(stock["today"]), len(stock["expired"])), (1, 0, 0))

    def test_daily_notice_once(self):
        self.make_batch("Медовик", 2, days=0)
        notice = self.client.get("/api/notice").json()
        self.assertTrue(notice["show"])
        self.assertEqual(notice["today"], [{"product_name": "Медовик", "quantity": 2}])
        self.assertFalse(self.client.get("/api/notice").json()["show"])

    def test_no_notice_when_expiring_page_opened_first(self):
        self.make_batch("Медовик", 2, days=0)
        self.assertFalse(self.client.get("/api/notice?skip=true").json()["show"])
        self.assertFalse(self.client.get("/api/notice").json()["show"])


class AdminProductsTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("admin")

    def test_add_edit_delete(self):
        response = self.client.post("/api/admin/products", json={
            "name": "  Медовик ", "fridge_storage_time": 3, "category": "Десерты",
        })
        product_id = response.json()["id"]
        [product] = self.client.get("/api/admin/products").json()
        self.assertEqual((product["name"], product["category"]), ("Медовик", "Десерты"))
        response = self.client.post("/api/admin/products", json={"name": "медовик", "fridge_storage_time": 2})
        self.assertIn("уже есть в справочнике", response.json()["detail"])

        self.db.new_delivery("Медовик", 4)
        self.client.put(f"/api/admin/products/{product_id}", json={
            "name": "Медовик классический", "fridge_storage_time": 5,
            "freezer_storage_time": 90, "category": None,
        })
        [product] = self.client.get("/api/admin/products").json()
        self.assertEqual(
            (product["name"], product["fridge_storage_time"], product["freezer_storage_time"], product["category"]),
            ("Медовик классический", 5, 90, None),
        )
        self.assertEqual(self.db.get_freezer_product("Медовик классический")["quantity"], 4)

        response = self.client.delete(f"/api/admin/products/{product_id}")
        self.assertIn("ещё есть в морозильнике", response.json()["detail"])

        actions = [change["action"] for change in self.changes()]
        self.assertIn("product_added", actions)
        self.assertIn("product_edited", actions)
        product_changes = [c for c in self.changes() if c["table_name"] == "products"]
        self.assertTrue(all(change["user_id"] == self.ADMIN_ID for change in product_changes))


class AdminUsersTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("admin")

    def test_add_user_who_can_log_in(self):
        response = self.client.post("/api/admin/users", json={
            "full_name": "Анна", "username": "anna", "password": "pass1", "role": "employee",
        })
        user_id = response.json()["id"]
        anna = self.client_for()
        self.login("anna", "pass1", client=anna)
        self.assertEqual(anna.get("/api/auth/me").json()["full_name"], "Анна")

        added = self.changes("user_added")[-1]
        self.assertEqual((added["user_id"], added["table_name"]), (self.ADMIN_ID, "users"))
        self.assertIn(f"Анна (№ {user_id})", added["details"])

        for body, message in (
            ({"username": "ADMIN"}, "уже занят"),
            ({"username": "анна петровна"}, "В логине можно"),
            ({"password": "1"}, "не короче"),
            ({"role": "boss"}, "Выберите роль"),
            ({"full_name": " "}, "Имя"),
        ):
            form = {"full_name": "Б", "username": "b", "password": "pass1", "role": "employee", **body}
            self.assertIn(message, self.client.post("/api/admin/users", json=form).json()["detail"])

    def test_update_other_user(self):
        employee = self.client_for()
        self.login("employee", client=employee)
        url = f"/api/admin/users/{self.EMPLOYEE_ID}"

        self.client.patch(url, json={"role": "admin"})
        self.assertEqual(employee.get("/api/admin/products").status_code, 200)
        self.client.patch(url, json={"is_active": False})
        self.assertEqual(employee.get("/api/auth/me").status_code, 401)
        self.client.patch(url, json={"is_active": True, "username": "worker", "password": "pass2", "full_name": "Пётр"})
        self.login("worker", "pass2", client=employee)

        actions = [change["action"] for change in self.changes()]
        for action in ("user_role", "user_access", "account_changed", "row_changed"):
            self.assertIn(action, actions)

    def test_bot_user_gets_login(self):
        self.db.add_user(123456789, "Иван")  # сотрудник из Telegram-бота, без логина
        url = "/api/admin/users/123456789"
        self.assertIn("Задайте логин", self.client.patch(url, json={"password": "pass1"}).json()["detail"])
        self.assertIn("Задайте пароль", self.client.patch(url, json={"username": "ivan"}).json()["detail"])
        self.assertEqual(self.client.patch(url, json={"username": "ivan", "password": "pass1"}).status_code, 200)
        self.login("ivan", "pass1", client=self.client_for())

    def test_cannot_remove_own_rights(self):
        url = f"/api/admin/users/{self.ADMIN_ID}"
        self.assertIn("Нельзя лишить себя прав", self.client.patch(url, json={"role": "employee"}).json()["detail"])
        self.assertIn("Нельзя отключить доступ", self.client.patch(url, json={"is_active": False}).json()["detail"])
        user = self.db.get_user(self.ADMIN_ID)
        self.assertEqual((user["role"], user["is_active"]), ("admin", True))
        # Имя и пароль себе менять можно.
        self.assertEqual(self.client.patch(url, json={"full_name": "Главный"}).status_code, 200)


class TablesTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)
        self.batch = self.db.move_to_fridge("Медовик", 2)
        self.login("admin")

    def test_list_and_russian_columns(self):
        names = [table["name"] for table in self.client.get("/api/admin/tables").json()]
        self.assertEqual(names, ["products", "freezer", "fridge", "operations", "users", "errors"])
        data = self.client.get("/api/admin/tables/fridge").json()
        self.assertEqual(data["title"], "Холодильник")
        self.assertEqual(
            [column["label"] for column in data["columns"]],
            ["№ партии", "Товар", "Количество, шт.", "Добавлено", "Годен до"],
        )
        kinds = {column["name"]: column["kind"] for column in data["columns"]}
        self.assertEqual(kinds["expiration_date"], "date")  # календарь на клиенте
        product = next(column for column in data["columns"] if column["name"] == "product_name")
        self.assertEqual(product["options"], [{"value": "Медовик", "label": "Медовик"}])
        self.assertEqual(data["items"][0]["expiration_date"], self.batch["expiration_date"])
        self.assertEqual(self.client.get("/api/admin/tables/accounts").status_code, 404)

    def test_edit_cells_and_log(self):
        url = f"/api/admin/tables/fridge/rows/{self.batch['id']}"
        row = self.client.patch(url, json={"values": {"expiration_date": "2026-12-31"}}).json()
        self.assertEqual(row["expiration_date"], "2026-12-31")
        response = self.client.patch(url, json={"values": {"quantity": 0}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("не меньше 1", response.json()["detail"])

        change = self.changes("row_changed")[-1]
        self.assertEqual((change["user_id"], change["table_name"]), (self.ADMIN_ID, "fridge"))
        self.assertIn("Годен до", change["details"])

    def test_insert_and_delete(self):
        response = self.client.post("/api/admin/tables/freezer/rows", json={"values": {"product_name": "Медовик", "quantity": 1}})
        self.assertIn("уже есть", response.json()["detail"])  # товар уже в морозильнике
        self.db.new_product("Чизкейк", 2)
        row = self.client.post("/api/admin/tables/freezer/rows", json={"values": {"product_name": "Чизкейк", "quantity": 4}}).json()
        self.assertEqual(self.db.get_freezer_product("Чизкейк")["quantity"], 4)
        self.client.delete(f"/api/admin/tables/freezer/rows/{row['__rowid']}")
        self.assertIsNone(self.db.get_freezer_product("Чизкейк"))
        self.assertEqual([c["action"] for c in self.changes()][-2:], ["row_added", "row_deleted"])

    def test_cannot_remove_own_rights_in_table(self):
        response = self.client.patch(f"/api/admin/tables/users/rows/{self.ADMIN_ID}", json={"values": {"role": "employee"}})
        self.assertIn("Нельзя лишить себя прав", response.json()["detail"])
        response = self.client.delete(f"/api/admin/tables/users/rows/{self.ADMIN_ID}")
        self.assertIn("Нельзя удалить самого себя", response.json()["detail"])
        self.assertEqual(self.db.get_user(self.ADMIN_ID)["role"], "admin")


class LogsTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("admin")

    def test_operations_filters(self):
        self.db.new_product("Медовик", 3)
        self.db.new_product("Лосось", 3)
        self.db.new_delivery("Медовик", 2, user_id=self.EMPLOYEE_ID)
        self.db.new_delivery("Лосось", 4, user_id=self.ADMIN_ID)
        data = self.client.get("/api/admin/logs/operations", params={"user": self.EMPLOYEE_ID}).json()
        self.assertEqual([row["product_name"] for row in data["items"]], ["Медовик"])
        data = self.client.get("/api/admin/logs/operations", params={"q": "лос", "type": "delivery"}).json()
        self.assertEqual(data["total"], 1)
        data = self.client.get("/api/admin/logs/operations", params={"date_to": "2000-01-01"}).json()
        self.assertEqual(data["total"], 0)

    def test_server_errors_are_logged(self):
        with mock.patch.object(Database, "fridge_batches_list", side_effect=RuntimeError("сломалось")):
            response = self.client.get("/api/stock")
        self.assertEqual(response.status_code, 500)
        self.assertIn("Ошибка записана в журнал", response.json()["detail"])
        errors = self.client.get("/api/admin/logs/errors").json()["items"]
        self.assertEqual(errors[0]["error_type"], "RuntimeError")
        self.assertIn("GET /api/stock", errors[0]["error_message"])
        self.assertIsNotNone(errors[0]["created_at"])

    def test_validation_errors_are_logged(self):
        response = self.client.post("/api/delivery", json={"product_id": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.errors()[-1]["error_type"], "RequestValidationError")

    def test_changes_and_server_log(self):
        self.client.post("/api/admin/users", json={"full_name": "Анна", "username": "anna", "password": "pass1", "role": "employee"})
        changes = self.client.get("/api/admin/logs/changes", params={"q": "анна"}).json()
        self.assertIn("user_added", [row["action"] for row in changes["items"]])

        server = self.client.get("/api/admin/logs/server").json()
        self.assertFalse(server["exists"])
        (self.temp_path / "app.log").write_text("".join(f"строка {n}\n" for n in range(500)), encoding="utf-8")
        lines = self.client.get("/api/admin/logs/server").json()["lines"]
        self.assertEqual((len(lines), lines[0]), (100, "строка 499"))


class BackupsTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.login("admin")

    def test_create_restore_delete(self):
        name = self.client.post("/api/admin/backups").json()["name"]
        self.assertEqual([file["name"] for file in self.client.get("/api/admin/backups").json()], [name])
        response = self.client.get(f"/api/admin/backups/{name}")
        self.assertTrue(response.content.startswith(b"SQLite format 3"))

        self.db.delete_product("Медовик")
        saved = self.client.post(f"/api/admin/backups/{name}/restore").json()["saved"]
        self.assertTrue(saved.startswith("before_restore_"))
        self.assertIsNotNone(self.db.get_product("Медовик"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

        # Журнал не откатился: запись о создании копии осталась.
        self.assertIn("backup_created", [change["action"] for change in self.changes()])

        self.client.delete(f"/api/admin/backups/{name}")
        self.assertEqual(self.client.get(f"/api/admin/backups/{name}").status_code, 404)
        actions = [change["action"] for change in self.changes()]
        for action in ("backup_created", "backup_restored", "backup_deleted"):
            self.assertIn(action, actions)

    def test_bad_names(self):
        for name in ("..%2Ftest.db", "missing.db", "notes.txt"):
            self.assertEqual(self.client.get(f"/api/admin/backups/{name}").status_code, 404, name)


class FrontendTest(ApiTestCase):
    def test_not_built_message(self):
        response = self.client.get("/admin/tables")
        self.assertEqual(response.status_code, 503)
        self.assertIn("npm run build", response.text)

    def test_spa_fallback(self):
        dist = self.temp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<div id=app></div>", encoding="utf-8")
        response = self.client.get("/admin/tables/fridge")
        self.assertEqual(response.text, "<div id=app></div>")
        self.assertEqual(self.client.get("/api/nope").status_code, 404)

    def test_icons_from_dist_root(self):
        dist = self.temp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<div id=app></div>", encoding="utf-8")
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
        response = self.client.get("/favicon.svg")
        self.assertEqual((response.text, response.headers["content-type"]), ("<svg/>", "image/svg+xml"))
        self.assertEqual(self.client.get("/manifest.webmanifest").headers["content-type"], "application/manifest+json")
        # Файлы вне dist недоступны.
        self.assertEqual(self.client.get("/..%2Fsecret_key").text, "<div id=app></div>")


if __name__ == "__main__":
    unittest.main()
