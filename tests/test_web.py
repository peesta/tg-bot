"""Сайт: вход, разный вид для ролей, разделы сотрудника и администратора."""
import unittest
from unittest import mock

from storage.db import Database
from tests.helpers import ERROR_TEXT, WebTestCase, set_expiration
from web.auth import (
    LoginLimiter, check_password, create_default_accounts, hash_password, limiter,
)
from web.utils import today


ADMIN_PAGES = (
    "/admin/products", "/admin/users", "/admin/db/", "/admin/db/products",
    "/admin/logs/operations", "/admin/logs/audit", "/admin/logs/errors",
    "/admin/logs/server", "/admin/google", "/admin/backups",
)
STAFF_PAGES = (
    "/", "/defrost", "/delivery", "/expiring", "/write-off", "/stock",
    "/history", "/profile",
)


class AuthTest(WebTestCase):
    def setUp(self):
        super().setUp()
        limiter._failures.clear()
        self.addCleanup(limiter._failures.clear)

    def test_default_accounts(self):
        admin = self.db.get_user_by_username("admin")
        employee = self.db.get_user_by_username("employee")
        self.assertEqual((admin["role"], employee["role"]), ("admin", "employee"))
        self.assertTrue(check_password(admin["password_hash"], "admin"))
        self.assertTrue(check_password(employee["password_hash"], "employee"))

    def test_default_accounts_not_recreated(self):
        self.db.delete_row("users", self.employee_id)
        create_default_accounts(self.db)
        self.assertIsNone(self.db.get_user_by_username("employee"))

    def test_pages_require_login(self):
        for path in STAFF_PAGES + ADMIN_PAGES:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/login", response.location)

    def test_no_registration(self):
        self.assertEqual(self.client.get("/register").status_code, 404)
        self.assertNotIn("регистрац", self.client.get("/login").text.replace("Регистрации нет", ""))

    def test_login_and_logout(self):
        response = self.login("admin")
        self.assertEqual(response.location, "/")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIsNotNone(self.db.get_user(self.admin_id)["last_login"])

        self.post("/logout")
        self.assertEqual(self.client.get("/").status_code, 302)
        actions = [row["action"] for row in self.db.audit_list()[1]]
        self.assertEqual(actions, ["logout", "login"])

    def test_wrong_password(self):
        response = self.post("/login", {"username": "admin", "password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Неверный логин или пароль", response.text)
        self.assertEqual(self.db.audit_list(action="login_failed")[0], 1)

    def test_username_is_case_insensitive(self):
        self.login("ADMIN", "admin")

    def test_next_redirect_only_to_this_site(self):
        response = self.post(
            "/login?next=/stock", {"username": "admin", "password": "admin"}
        )
        self.assertEqual(response.location, "/stock")
        self.post("/logout")
        response = self.post(
            "/login?next=//evil.example", {"username": "admin", "password": "admin"}
        )
        self.assertEqual(response.location, "/")

    def test_rate_limit(self):
        for _ in range(LoginLimiter.MAX_FAILURES):
            self.post("/login", {"username": "admin", "password": "nope"})
        response = self.post("/login", {"username": "admin", "password": "admin"})
        self.assertIn("Слишком много неудачных попыток", response.text)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_csrf_required(self):
        response = self.client.post("/login", data={"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 400)
        self.login("admin")
        self.db.new_product("Медовик", 3)
        response = self.client.post("/delivery", data={"product_id": 1, "quantity": 5})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.db.get_freezer_product("Медовик"))

    def test_disabled_user_is_logged_out(self):
        self.login("employee")
        self.db.set_user_active(self.employee_id, False)
        self.assertEqual(self.client.get("/").status_code, 302)
        response = self.post("/login", {"username": "employee", "password": "employee"})
        self.assertIn("Доступ отключён", response.text)

    def test_password_reset_ends_other_sessions(self):
        self.login("employee")
        self.db.set_user_password(self.employee_id, hash_password("new-secret"))
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_weak_password_warning_and_change(self):
        self.login("employee")
        self.assertIn("Пароль по умолчанию небезопасен", self.client.get("/").text)

        response = self.post("/profile", {
            "current_password": "employee", "new_password": "123",
            "repeat_password": "123",
        }, follow_redirects=True)
        self.assertIn("не короче 6", response.text)
        response = self.post("/profile", {
            "current_password": "wrong", "new_password": "secret1",
            "repeat_password": "secret1",
        }, follow_redirects=True)
        self.assertIn("Текущий пароль указан неверно", response.text)

        response = self.post("/profile", {
            "current_password": "employee", "new_password": "secret1",
            "repeat_password": "secret1",
        }, follow_redirects=True)
        self.assertIn("Пароль изменён", response.text)
        self.assertNotIn("Пароль по умолчанию небезопасен", response.text)
        # Текущая сессия продолжает работать, пароль сменился.
        self.assertEqual(self.client.get("/").status_code, 200)
        user = self.db.get_user(self.employee_id)
        self.assertTrue(check_password(user["password_hash"], "secret1"))


class RolesTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()

    def test_employee_has_no_admin_pages(self):
        self.login("employee")
        for path in STAFF_PAGES:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for path in ADMIN_PAGES:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.post("/admin/products", {"name": "X"}).status_code, 403)
        self.assertEqual(self.post("/admin/db/products/new").status_code, 403)

    def test_admin_sees_everything(self):
        self.login("admin")
        for path in STAFF_PAGES + ADMIN_PAGES:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_layouts_differ(self):
        self.login("employee")
        page = self.client.get("/").text
        self.assertIn('class="role-employee"', page)
        self.assertIn("Мои действия сегодня", page)
        self.assertNotIn("Администрирование", page)
        self.assertNotIn("/admin/", page)

        self.post("/logout")
        self.login("admin")
        page = self.client.get("/").text
        self.assertIn('class="role-admin"', page)
        self.assertIn("Администрирование", page)
        self.assertIn("/admin/db/", page)
        self.assertIn("операций сегодня", page)


class StaffPagesTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.db.new_product("Медовик", 3)
        self.db.new_product("Филадельфия", 2)
        self.login("employee")

    def product_id(self, name):
        return self.db.get_product(name)["id"]

    def test_delivery(self):
        response = self.post(
            "/delivery", {"product_id": self.product_id("Медовик"), "quick": "2"},
            follow_redirects=True,
        )
        self.assertIn("Медовик — 2 шт", response.text)
        self.post("/delivery", {"product_id": self.product_id("Медовик"), "quantity": "5"})
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 7)

        _, operations = self.db.operations_log()
        self.assertEqual(operations[0]["created_by"], self.employee_id)

        response = self.post(
            "/delivery", {"product_id": self.product_id("Медовик"), "quantity": "0"},
            follow_redirects=True,
        )
        self.assertIn("целое число", response.text)

    def test_delivery_keeps_search_and_page(self):
        response = self.post("/delivery", {
            "product_id": self.product_id("Медовик"), "quick": "1",
            "q": "мед", "page": "2",
        })
        self.assertIn("q=", response.location)
        self.assertIn("page=2", response.location)

    def test_defrost(self):
        self.db.new_delivery("Медовик", 5)
        product_id = self.db.get_freezer_product("Медовик")["id"]
        page = self.client.get("/defrost").text
        self.assertIn("Медовик", page)
        self.assertIn('value="3"', page)  # быстрые кнопки 1, 2, 3

        response = self.post(
            "/defrost", {"product_id": product_id, "quantity": "2"},
            follow_redirects=True,
        )
        self.assertIn("Добавлено: Медовик — 2 шт", response.text)
        self.assertIn("Годен до", response.text)
        batch = self.db.fridge_batches_list()[0]
        self.assertEqual(batch["quantity"], 2)
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 3)

        response = self.post(
            "/defrost", {"product_id": product_id, "quantity": "10"},
            follow_redirects=True,
        )
        self.assertIn("только 3 шт", response.text)

        self.post("/defrost", {"product_id": product_id, "quick": "3"})
        self.assertIsNone(self.db.get_freezer_product("Медовик"))
        response = self.post(
            "/defrost", {"product_id": product_id, "quick": "1"},
            follow_redirects=True,
        )
        self.assertIn("уже нет в морозильнике", response.text)

    def test_defrost_search(self):
        self.db.new_delivery("Медовик", 5)
        self.db.new_delivery("Филадельфия", 5)
        page = self.client.get("/defrost?q=фила").text
        self.assertIn("Филадельфия", page)
        self.assertNotIn("Медовик", page)
        self.assertIn("ничего не найдено", self.client.get("/defrost?q=пицца").text)

    def make_batch(self, name="Медовик", quantity=5, days=None):
        self.db.new_delivery(name, quantity)
        batch = self.db.move_to_fridge(name, quantity)
        if days is not None:
            set_expiration(self.db, batch["id"], days)
        return batch["id"]

    def test_write_off_with_reason(self):
        batch_id = self.make_batch()
        self.assertIn("Медовик — 5 шт.", self.client.get("/write-off").text)
        self.assertEqual(self.client.get(f"/write-off/{batch_id}").status_code, 200)

        response = self.post(f"/write-off/{batch_id}", {
            "operation": "write_off", "reason": "damaged", "quantity": "2",
        }, follow_redirects=True)
        self.assertIn("Списано: Медовик - 2 Шт. Причина: Повреждено", response.text)
        self.assertEqual(self.db.get_fridge_batch(batch_id)["quantity"], 3)

    def test_write_off_other_reason(self):
        batch_id = self.make_batch()
        response = self.post(f"/write-off/{batch_id}", {
            "operation": "write_off", "reason": "other", "reason_text": " ",
            "quantity": "1",
        }, follow_redirects=True)
        self.assertIn("Напишите причину", response.text)

        self.post(f"/write-off/{batch_id}", {
            "operation": "write_off", "reason": "other",
            "reason_text": "Уронили  на пол", "whole": "1",
        })
        self.assertIsNone(self.db.get_fridge_batch(batch_id))
        _, rows = self.db.operations_log(operation_type="write_off")
        self.assertEqual((rows[0]["reason"], rows[0]["quantity"]), ("Уронили на пол", 5))

    def test_write_off_validation(self):
        batch_id = self.make_batch()
        response = self.post(f"/write-off/{batch_id}", {
            "operation": "write_off", "quantity": "1",
        }, follow_redirects=True)
        self.assertIn("Выберите причину", response.text)
        response = self.post(f"/write-off/{batch_id}", {
            "operation": "sale", "quantity": "6",
        }, follow_redirects=True)
        self.assertIn("от 1 до 5", response.text)
        self.assertEqual(self.post(f"/write-off/{batch_id}", {"operation": "x"}).status_code, 400)
        response = self.client.get("/write-off/999", follow_redirects=True)
        self.assertIn("Этой партии уже нет", response.text)

    def test_sale(self):
        batch_id = self.make_batch()
        response = self.post(f"/write-off/{batch_id}", {
            "operation": "sale", "quantity": "5",
        }, follow_redirects=True)
        self.assertIn("Продано: Медовик - 5 Шт. Партия закрыта полностью.", response.text)
        self.assertEqual(self.db.operations_log(operation_type="sale")[0], 1)

    def test_expiring_and_clear_all(self):
        self.make_batch("Медовик", 2, days=0)
        self.make_batch("Филадельфия", 3, days=-1)
        self.make_batch("Медовик", 4, days=2)

        page = self.client.get("/expiring").text
        self.assertIn("Сегодня заканчивается срок годности", page)
        self.assertIn("Срок годности уже истёк", page)
        self.assertIn("Списать всё (2 парт.)", page)

        response = self.post("/expiring/clear", follow_redirects=True)
        self.assertIn("Списано просроченных партий: 2", response.text)
        self.assertEqual(len(self.db.fridge_batches_list()), 1)
        response = self.post("/expiring/clear", follow_redirects=True)
        self.assertIn("нет", self.flashes(response)[-1])

    def test_stock(self):
        self.make_batch("Медовик", 2, days=0)
        self.make_batch("Филадельфия", 3, days=-1)
        self.db.new_delivery("Медовик", 7)
        page = self.client.get("/stock").text
        for text in ("Срок истекает сегодня", "Просрочено", "Морозильник", "7"):
            self.assertIn(text, page)
        self.assertNotIn("Годные", page)

    def test_history(self):
        batch_id = self.make_batch()
        self.post(f"/write-off/{batch_id}", {
            "operation": "write_off", "reason": "staff", "quantity": "1",
        })
        self.post(f"/write-off/{batch_id}", {"operation": "sale", "quantity": "1"})
        page = self.client.get("/history").text
        self.assertIn("Для сотрудника", page)
        self.assertIn("Сотрудник", page)
        self.assertEqual(page.count("<tr>"), 2)  # заголовок и одно списание

    def test_dashboard_shows_my_operations(self):
        self.post("/delivery", {"product_id": self.product_id("Медовик"), "quick": "3"})
        page = self.client.get("/").text
        self.assertIn("Заморозка", page)
        self.assertIn("Медовик — 3 шт", page)


class DailyNoticeTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)
        batch = self.db.move_to_fridge("Медовик", 2)
        set_expiration(self.db, batch["id"], 0)

    def test_once_a_day(self):
        self.login("employee")
        page = self.client.get("/stock").text
        self.assertIn("⚠ Сегодня заканчивается срок годности", page)
        self.assertIn("Медовик — 2 шт", page)
        self.assertNotIn("⚠ Сегодня заканчивается срок годности", self.client.get("/stock").text)

        # Второй вход в тот же день — без уведомления.
        self.post("/logout")
        self.login("employee")
        self.assertNotIn("⚠ Сегодня заканчивается срок годности", self.client.get("/stock").text)

    def test_not_shown_when_expiring_opened_first(self):
        self.login("employee")
        self.client.get("/expiring")
        self.assertNotIn("Перейти к списанию", self.client.get("/").text)

    def test_nothing_expiring(self):
        set_expiration(self.db, self.db.fridge_batches_list()[0]["id"], 5)
        self.login("employee")
        self.assertNotIn("Перейти к списанию", self.client.get("/").text)
        self.assertFalse(self.db.mark_daily_notification(self.employee_id, today()))


class AdminProductsTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.login("admin")

    def test_add_product(self):
        response = self.post("/admin/products", {
            "name": "  Медовик  ", "fridge_storage_time": "3",
            "freezer_storage_time": "", "category": "Десерты",
        }, follow_redirects=True)
        self.assertIn("Товар «Медовик» добавлен", response.text)
        product = self.db.get_product("Медовик")
        self.assertEqual((product["category"], product["freezer_storage_time"]), ("Десерты", None))

        response = self.post("/admin/products", {
            "name": "медовик", "fridge_storage_time": "2",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("уже есть в справочнике", response.text)

        for days in ("0", "abc", "366"):
            response = self.post("/admin/products", {
                "name": "Чизкейк", "fridge_storage_time": days,
            })
            self.assertEqual(response.status_code, 400, days)
        self.assertIsNone(self.db.get_product("Чизкейк"))
        self.assertEqual(self.db.audit_list(action="product_created")[0], 1)

    def test_edit_product(self):
        self.db.new_product("Медовик", 3)
        self.db.new_product("Чизкейк", 3)
        self.db.new_delivery("Медовик", 4)
        product_id = self.db.get_product("Медовик")["id"]
        self.assertIn("В морозильнике: 4 шт.", self.client.get(f"/admin/products/{product_id}").text)

        self.post(f"/admin/products/{product_id}", {
            "name": "Медовик классический", "fridge_storage_time": "5",
            "freezer_storage_time": "90", "category": "",
        })
        product = self.db.get_product("Медовик классический")
        self.assertEqual(
            (product["fridge_storage_time"], product["freezer_storage_time"]), (5, 90)
        )
        self.assertEqual(self.db.get_freezer_product("Медовик классический")["quantity"], 4)
        _, actions = self.db.audit_list(action="product_updated")
        self.assertIn("Медовик → Медовик классический", actions[0]["details"])

        response = self.post(f"/admin/products/{product_id}", {
            "name": "ЧИЗКЕЙК", "fridge_storage_time": "5",
        })
        self.assertEqual(response.status_code, 400)
        # Поменять регистр букв своему названию можно.
        self.post(f"/admin/products/{product_id}", {
            "name": "медовик классический", "fridge_storage_time": "5",
        })
        self.assertIsNotNone(self.db.get_product("медовик классический"))

    def test_delete_product(self):
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 1)
        product_id = self.db.get_product("Медовик")["id"]

        response = self.post(f"/admin/products/{product_id}/delete", follow_redirects=True)
        self.assertIn("ещё есть в морозильнике", response.text)

        self.db.move_to_fridge("Медовик", 1)
        response = self.post(f"/admin/products/{product_id}/delete", follow_redirects=True)
        self.assertIn("удалён", response.text)
        self.assertIsNone(self.db.get_product("Медовик"))
        response = self.client.get(f"/admin/products/{product_id}", follow_redirects=True)
        self.assertIn("уже нет в справочнике", response.text)

    def test_search(self):
        self.db.new_product("Медовик", 3, None, "Десерты")
        self.db.new_product("Лосось", 3, None, "Рыба")
        page = self.client.get("/admin/products?q=десерт").text
        self.assertIn("Медовик", page)
        self.assertNotIn("Лосось", page)


class AdminUsersTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.login("admin")

    def add_user(self, **data):
        form = {"full_name": "Анна", "username": "anna", "password": "secret1", "role": "employee"}
        form.update(data)
        return self.post("/admin/users", form, follow_redirects=True)

    def test_add_user_who_can_log_in(self):
        response = self.add_user()
        self.assertIn("может входить на сайт с логином «anna»", response.text)
        user = self.db.get_user_by_username("anna")
        self.assertEqual((user["role"], user["is_active"]), ("employee", True))

        other = self.app.test_client()
        self.login("anna", "secret1", client=other)
        self.assertIn("Здравствуйте, Анна", other.get("/").text)

    def test_add_user_validation(self):
        self.assertIn("уже занят", self.add_user(username="ADMIN").text)
        self.assertIn("не короче 6", self.add_user(password="123").text)
        self.assertIn("Укажите имя", self.add_user(full_name=" ").text)
        self.assertIn("В логине можно", self.add_user(username="анна петровна").text)
        self.assertIn("Выберите роль", self.add_user(role="boss").text)
        self.assertIsNone(self.db.get_user_by_username("anna"))

    def test_role_access_password(self):
        user_id = self.db.add_user("anna", "Анна", hash_password("secret1"))
        url = f"/admin/users/{user_id}"
        anna = self.app.test_client()
        self.login("anna", "secret1", client=anna)

        self.post(url, {"action": "role", "role": "admin"})
        self.assertEqual(self.db.get_user(user_id)["role"], "admin")
        self.assertEqual(anna.get("/admin/products").status_code, 200)

        self.post(url, {"action": "access", "is_active": "0"})
        self.assertFalse(self.db.get_user(user_id)["is_active"])
        self.assertEqual(anna.get("/").status_code, 302)  # выкинуло с сайта

        self.post(url, {"action": "access", "is_active": "1"})
        self.post(url, {"action": "password", "password": "another1"})
        self.login("anna", "another1", client=anna)

        self.post(url, {"action": "profile", "full_name": "Анна П.", "username": "anna.p"})
        user = self.db.get_user(user_id)
        self.assertEqual((user["full_name"], user["username"]), ("Анна П.", "anna.p"))
        self.assertEqual(self.db.audit_list(action="user_updated")[0], 5)

    def test_cannot_change_own_role_or_access(self):
        url = f"/admin/users/{self.admin_id}"
        self.assertIn("свою роль и доступ изменить нельзя", self.client.get(url).text)
        response = self.post(url, {"action": "role", "role": "employee"}, follow_redirects=True)
        self.assertIn("Свою роль и доступ изменить нельзя", response.text)
        self.post(url, {"action": "access", "is_active": "0"})
        user = self.db.get_user(self.admin_id)
        self.assertEqual((user["role"], user["is_active"]), ("admin", True))

    def test_edited_user_does_not_replace_current_user_in_layout(self):
        page = self.client.get(f"/admin/users/{self.employee_id}").text
        self.assertIn('class="role-admin"', page)
        self.assertIn("<span>admin</span>", page)  # в боковой панели — вошедший
        self.assertIn("Роль и доступ", page)


class DatabaseEditorTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.db.new_product("Медовик", 3)
        self.login("admin")

    def test_tables_list(self):
        page = self.client.get("/admin/db/").text
        for table in ("products", "freezer", "fridge", "operations", "users", "errors", "audit_log"):
            self.assertIn(f"/admin/db/{table}", page)
        self.assertEqual(self.client.get("/admin/db/no_such_table").status_code, 404)

    def test_insert_edit_delete(self):
        response = self.post("/admin/db/freezer/new", {
            "col_product_name": "Медовик", "col_quantity": "4",
        }, follow_redirects=True)
        self.assertIn("Строка добавлена", response.text)
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 4)
        rowid = self.db.get_freezer_product("Медовик")["id"]

        response = self.post(f"/admin/db/freezer/{rowid}", {
            "col_product_name": "Медовик", "col_quantity": "абв",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Нужно целое число", response.text)

        response = self.post(f"/admin/db/freezer/{rowid}", {
            "col_product_name": "Медовик", "col_quantity": "0",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("CHECK constraint failed", response.text)

        self.post(f"/admin/db/freezer/{rowid}", {
            "col_product_name": "Медовик", "col_quantity": "9",
        })
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 9)

        self.post(f"/admin/db/freezer/{rowid}/delete")
        self.assertIsNone(self.db.get_freezer_product("Медовик"))

        actions = [row["action"] for row in self.db.audit_list()[1]]
        self.assertEqual(actions[:3], ["db_delete", "db_update", "db_insert"])
        _, rows = self.db.audit_list(action="db_update")
        self.assertIn("quantity: 4 → 9", rows[0]["details"])

    def test_null_and_empty_values(self):
        product_id = self.db.get_product("Медовик")["id"]
        self.post(f"/admin/db/products/{product_id}", {
            "col_name": "Медовик", "col_fridge_storage_time": "3",
            "col_freezer_storage_time": "", "col_category": "Десерты",
        })
        self.assertEqual(self.db.get_product("Медовик")["category"], "Десерты")
        self.post(f"/admin/db/products/{product_id}", {
            "col_name": "Медовик", "col_fridge_storage_time": "3",
            "col_category": "Десерты", "null_category": "1",
        })
        self.assertIsNone(self.db.get_product("Медовик")["category"])

    def test_password_hash_hidden(self):
        page = self.client.get("/admin/db/users").text
        self.assertNotIn("password_hash", page)
        self.assertNotIn("scrypt", page)
        page = self.client.get(f"/admin/db/users/{self.employee_id}").text
        self.assertNotIn("password_hash", page)

        self.post(f"/admin/db/users/{self.employee_id}", {
            "col_id": str(self.employee_id), "col_username": "employee",
            "col_full_name": "Новое имя", "col_role": "employee",
            "col_is_active": "1",
        })
        user = self.db.get_user(self.employee_id)
        self.assertEqual(user["full_name"], "Новое имя")
        self.assertTrue(check_password(user["password_hash"], "employee"))

    def test_audit_log_read_only(self):
        page = self.client.get("/admin/db/audit_log").text
        self.assertNotIn("Добавить строку", page)
        self.assertEqual(self.post("/admin/db/audit_log/new").status_code, 403)
        self.assertEqual(self.post("/admin/db/audit_log/1/delete").status_code, 403)
        self.assertEqual(self.post("/admin/db/audit_log/1", {"col_action": "x"}).status_code, 403)
        self.assertEqual(self.client.get("/admin/db/audit_log/1").status_code, 200)

    def test_search_sort_and_csv(self):
        self.db.new_product("Чизкейк", 2)
        page = self.client.get("/admin/db/products?q=чиз").text
        self.assertIn("Чизкейк", page)
        self.assertNotIn("Медовик", page)
        page = self.client.get("/admin/db/products?sort=name&desc=1").text
        self.assertLess(page.index("Чизкейк"), page.index("Медовик"))

        response = self.client.get("/admin/db/products/export.csv")
        self.assertEqual(response.mimetype, "text/csv")
        lines = response.get_data(as_text=True).lstrip("﻿").splitlines()
        self.assertEqual(lines[0], "name;fridge_storage_time;freezer_storage_time;category")
        self.assertEqual(len(lines), 3)
        self.assertNotIn("password_hash", self.client.get("/admin/db/users/export.csv").text)


class LogsTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.login("admin")

    def test_operations_filters_and_csv(self):
        self.db.new_product("Медовик", 3)
        self.db.new_product("Лосось", 3)
        self.db.new_delivery("Медовик", 2, user_id=self.employee_id)
        self.db.new_delivery("Лосось", 4, user_id=self.admin_id)

        page = self.client.get(f"/admin/logs/operations?user={self.employee_id}").text
        self.assertIn("Медовик", page)
        self.assertNotIn("<td>Лосось</td>", page)
        page = self.client.get("/admin/logs/operations?q=лос&type=delivery").text
        self.assertIn("<td>Лосось</td>", page)
        page = self.client.get("/admin/logs/operations?date_to=2000-01-01").text
        self.assertIn("Записей не найдено", page)

        response = self.client.get("/admin/logs/operations.csv?q=мед")
        text = response.get_data(as_text=True)
        self.assertIn("Медовик;2", text.replace("Заморозка;", ""))
        self.assertNotIn("Лосось", text)

    def test_audit(self):
        self.post("/logout")
        self.post("/login", {"username": "admin", "password": "wrong"})
        self.login("admin")
        page = self.client.get("/admin/logs/audit").text
        self.assertIn("Неудачный вход", page)
        self.assertIn("Логин: admin", page)
        page = self.client.get("/admin/logs/audit?action=logout").text
        self.assertIn("Выход", page)
        self.assertNotIn("Неудачный вход</strong>", page)

    def test_errors_are_logged_and_shown(self):
        with mock.patch.object(Database, "fridge_batches_list", side_effect=RuntimeError("сломалось")):
            response = self.client.get("/stock")
        self.assertEqual(response.status_code, 500)
        self.assertIn(ERROR_TEXT, response.text)

        total, errors = self.db.errors_list()
        self.assertEqual(total, 1)
        self.assertEqual(errors[0]["error_type"], "RuntimeError")
        self.assertIn("GET /stock", errors[0]["error_message"])
        page = self.client.get("/admin/logs/errors").text
        self.assertIn("RuntimeError", page)
        self.assertIn("сломалось", page)

    def test_server_log(self):
        self.assertIn("Файла журнала пока нет", self.client.get("/admin/logs/server").text)
        log_file = self.temp_path / "app.log"
        log_file.write_text("".join(f"строка {n}\n" for n in range(500)), encoding="utf-8")
        page = self.client.get("/admin/logs/server").text
        self.assertIn("строка 499", page)
        self.assertNotIn("строка 399", page)
        self.assertIn("строка 200", self.client.get("/admin/logs/server?lines=300").text)


class BackupsTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.skip_daily_notice()
        self.db.new_product("Медовик", 3)
        self.login("admin")

    def backup_names(self):
        return sorted(path.name for path in (self.temp_path / "backups").glob("*.db"))

    def test_create_download_restore_delete(self):
        self.post("/admin/backups")
        [name] = self.backup_names()
        self.assertTrue(name.startswith("manual_"))
        self.assertIn(name, self.client.get("/admin/backups").text)

        response = self.client.get(f"/admin/backups/{name}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"SQLite format 3"))
        response.close()

        self.db.delete_product("Медовик")
        response = self.post(f"/admin/backups/{name}/restore", follow_redirects=True)
        self.assertIn("База восстановлена", response.text)
        self.assertIsNotNone(self.db.get_product("Медовик"))
        self.assertEqual(len(self.backup_names()), 2)  # + before_restore_…

        self.post(f"/admin/backups/{name}/delete")
        self.assertNotIn(name, self.backup_names())

    def test_bad_names(self):
        for name in ("..%2Ftest.db", "missing.db", "notes.txt"):
            self.assertEqual(self.client.get(f"/admin/backups/{name}").status_code, 404, name)
            self.assertEqual(self.post(f"/admin/backups/{name}/delete").status_code, 404, name)


if __name__ == "__main__":
    unittest.main()
