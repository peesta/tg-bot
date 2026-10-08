"""Проверка безопасности сайта перед выкладкой на сервер.

Каждый тест описывает, как сайт ДОЛЖЕН себя вести. Упавший тест —
найденная уязвимость (подробности в сообщении теста), прошедший —
защита работает и не должна сломаться при будущих правках.

Запуск: python -m unittest tests.test_security -v
"""
import base64
import json
import re
import statistics
import threading
import time
from pathlib import Path
from unittest import mock

from itsdangerous import TimestampSigner

from api import create_app
from api.auth import limiter
from api.deps import session_token
from storage.accounts import Accounts, check_password
from storage.db import Database
from tests.helpers import ApiTestCase, HEADERS


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_ROUTES = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout")}


def api_routes(app) -> list[tuple[str, str]]:
    """Все (метод, адрес) API с подставленными параметрами пути."""
    result = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: "products" if m[1] == "name" else "1", path)
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method != "HEAD":
                result.append((method, concrete))
    return result


def forged_cookie(session: dict, secret_key: str) -> str:
    """Cookie сессии в формате starlette SessionMiddleware."""
    data = base64.b64encode(json.dumps(session).encode())
    return TimestampSigner(secret_key).sign(data).decode()


# ---------- Доступ: вход, роли, CSRF ----------

class AccessControlTest(ApiTestCase):

    def test_every_api_route_requires_login(self):
        """Без входа нельзя ни прочитать, ни изменить данные."""
        anonymous = self.client_for()
        for method, path in api_routes(self.app):
            if (method, path) in PUBLIC_ROUTES:
                continue
            with self.subTest(route=f"{method} {path}"):
                response = anonymous.request(method, path, json={})
                self.assertIn(response.status_code, (401, 404, 405), response.text)
                self.assertNotEqual(response.status_code, 200)

    def test_employee_cannot_use_any_admin_route(self):
        """Сотрудник не может вызвать ни один адрес администратора."""
        self.login("employee")
        for method, path in api_routes(self.app):
            if not path.startswith("/api/admin"):
                continue
            with self.subTest(route=f"{method} {path}"):
                response = self.client.request(method, path, json={"values": {}})
                self.assertEqual(response.status_code, 403, response.text)

    def test_unsafe_requests_without_header_are_rejected(self):
        """CSRF: изменения без X-Requested-With отклоняются ещё до входа."""
        self.login("admin")
        bare = self.client_for()
        bare.headers.pop("X-Requested-With")
        bare.cookies = self.client.cookies
        for method, path in api_routes(self.app):
            if method not in UNSAFE:
                continue
            with self.subTest(route=f"{method} {path}"):
                response = bare.request(method, path, json={})
                self.assertEqual(response.status_code, 403, response.text)
        # Форма с чужого сайта (text/plain, без заголовка) тоже не проходит.
        response = bare.post(
            "/api/admin/backups", content=b"x", headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(response.status_code, 403)

    def test_no_cors_for_foreign_sites(self):
        """Чужой сайт не получает разрешение CORS на запросы с заголовком."""
        response = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-requested-with",
            },
        )
        self.assertNotIn("access-control-allow-origin", response.headers)
        response = self.client.get("/api/auth/me", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_employee_cannot_escalate_through_any_field(self):
        """Сотрудник не может выдать себе права администратора."""
        self.login("employee")
        attempts = [
            ("PATCH", f"/api/admin/users/{self.EMPLOYEE_ID}", {"role": "admin"}),
            ("PATCH", f"/api/admin/tables/users/rows/{self.EMPLOYEE_ID}",
             {"values": {"role": "admin"}}),
            ("POST", "/api/auth/password",
             {"current_password": "employee", "new_password": "employee", "role": "admin"}),
        ]
        for method, path, body in attempts:
            self.client.request(method, path, json=body)
        self.assertEqual(self.accounts.get(self.EMPLOYEE_ID)["role"], "employee")


# ---------- Сессии ----------

class SessionTest(ApiTestCase):

    def test_forged_cookie_with_wrong_key_is_rejected(self):
        """Подделать сессию администратора без секретного ключа нельзя."""
        admin = self.accounts.get(self.ADMIN_ID)
        cookie = forged_cookie(
            {"user_id": self.ADMIN_ID, "auth": session_token(admin)}, "guessed-key"
        )
        client = self.client_for()
        client.cookies.set("session", cookie)
        self.assertEqual(client.get("/api/admin/users").status_code, 401)

    def test_session_needs_password_fingerprint(self):
        """Даже с ключом нельзя войти, зная только номер сотрудника."""
        client = self.client_for()
        client.cookies.set("session", forged_cookie({"user_id": self.ADMIN_ID}, "test"))
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_login_replaces_session(self):
        """Фиксация сессии: после входа старые данные сессии не сохраняются."""
        client = self.client_for()
        client.cookies.set("session", forged_cookie({"user_id": self.ADMIN_ID, "x": 1}, "test"))
        self.login("employee", client=client)
        self.assertEqual(client.get("/api/auth/me").json()["role"], "employee")

    def test_cookie_flags(self):
        """Cookie недоступна JavaScript и не уходит с чужих сайтов."""
        response = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin"}
        )
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_secure_cookie_when_https(self):
        app = create_app({
            "database": str(self.temp_path / "secure.db"), "secret_key": "k",
            "secure_cookies": True, "frontend_dist": str(self.temp_path / "dist"),
        })
        from fastapi.testclient import TestClient
        with TestClient(app, headers=HEADERS, base_url="https://testserver") as client:
            response = client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin"}
            )
        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_stolen_cookie_is_useless_after_logout(self):
        """УЯЗВИМОСТЬ, если падает: сессия хранится только в cookie, и
        «Выйти» её не отменяет. Укравший cookie (чужой планшет, перехват
        по HTTP) остаётся администратором до 12 часов после выхода."""
        self.login("admin")
        stolen = self.client.cookies.get("session")
        self.client.post("/api/auth/logout")

        attacker = self.client_for()
        attacker.cookies.set("session", stolen)
        self.assertEqual(
            attacker.get("/api/admin/users").status_code, 401,
            "cookie, сохранённая до выхода, всё ещё даёт доступ",
        )


# ---------- Пароли и вход ----------

class PasswordPolicyTest(ApiTestCase):

    def test_no_known_default_passwords(self):
        """УЯЗВИМОСТЬ, если падает: при первом запуске создаются admin/admin
        и employee/employee. Если забыть их сменить, на сервер войдёт любой,
        кто попробует эти пароли (боты делают это автоматически)."""
        fresh = create_app({
            "database": str(self.temp_path / "fresh.db"), "secret_key": "k",
            "frontend_dist": str(self.temp_path / "dist"),
        })
        accounts: Accounts = fresh.state.accounts
        for username in ("admin", "employee"):
            user = accounts.get_by_username(username)
            with self.subTest(username=username):
                self.assertFalse(
                    user is not None and check_password(user["password_hash"], username),
                    f"на свежем сервере работает {username}/{username}",
                )

    def test_restore_does_not_bring_back_default_passwords(self):
        """Восстановление старой копии без учётных записей не должно
        создавать admin/admin."""
        with self.db.cursor() as cursor:
            cursor.execute("DELETE FROM accounts")
        self.db.backup(str(self.temp_path / "backups" / "old.db"))
        self.accounts.create_user("Владелец", "owner", "Strong-Pass-2026", "admin")
        self.login("owner", "Strong-Pass-2026")
        self.client.post("/api/admin/backups/old.db/restore")
        user = self.accounts.get_by_username("admin")
        self.assertFalse(
            user is not None and check_password(user["password_hash"], "admin"),
            "после восстановления копии снова работает admin/admin",
        )

    def test_weak_passwords_are_rejected(self):
        """УЯЗВИМОСТЬ, если падает: пароль от 4 символов («1234»,
        «admin») подбирается за минуты даже с ограничением попыток."""
        self.login("admin")
        for weak in ("1234", "admin", "qwerty", "password"):
            with self.subTest(password=weak):
                response = self.client.post("/api/admin/users", json={
                    "full_name": "Тест", "username": f"u{len(weak)}{weak}",
                    "password": weak, "role": "admin",
                })
                self.assertEqual(response.status_code, 400, f"принят пароль «{weak}»")

    def test_password_hash_never_leaves_server(self):
        """Хеши паролей не отдаются ни в одном ответе."""
        self.login("admin")
        responses = [
            self.client.get("/api/auth/me"),
            self.client.get("/api/admin/users"),
            self.client.get("/api/admin/tables/users"),
            self.client.patch(f"/api/admin/users/{self.EMPLOYEE_ID}", json={"full_name": "Сотрудник"}),
            self.client.get("/api/dashboard"),
            self.client.get("/api/admin/logs/changes"),
        ]
        for response in responses:
            with self.subTest(url=str(response.url)):
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("password", response.text)
                self.assertNotIn("scrypt$", response.text)

    def test_table_editor_cannot_touch_accounts(self):
        """Через редактор таблиц нельзя подменить хеш пароля или логин."""
        self.login("admin")
        for body in (
            {"values": {"password_hash": "x"}},
            {"values": {'full_name" = \'x\', "role': "admin"}},
        ):
            response = self.client.patch(
                f"/api/admin/tables/users/rows/{self.EMPLOYEE_ID}", json=body
            )
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/admin/tables/accounts").status_code, 404)


class BruteForceTest(ApiTestCase):

    def wrong_login(self, username, client=None):
        return (client or self.client).post(
            "/api/auth/login", json={"username": username, "password": "wrong-pass"}
        )

    def test_same_login_is_blocked(self):
        for _ in range(limiter.MAX_FAILURES):
            self.assertEqual(self.wrong_login("admin").status_code, 401)
        self.assertEqual(self.wrong_login("admin").status_code, 429)
        # Правильный пароль после блокировки тоже не проверяется.
        response = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin"}
        )
        self.assertEqual(response.status_code, 429)

    def test_password_spraying_from_one_address_is_blocked(self):
        """УЯЗВИМОСТЬ, если падает: ограничение считается по паре
        (адрес, логин). С одного адреса можно перебирать пароли по всем
        логинам подряд (по 4 попытки на каждый) — и никогда не упереться
        в блокировку. А несуществующие логины бесконечно раздувают
        словарь попыток в памяти сервера."""
        statuses = []
        for number in range(60):
            for _ in range(limiter.MAX_FAILURES - 1):
                statuses.append(self.wrong_login(f"user{number}").status_code)
        self.assertIn(429, statuses, "240 неудачных входов с одного адреса — без блокировки")

    def test_login_does_not_reveal_which_usernames_exist(self):
        """УЯЗВИМОСТЬ, если падает: для несуществующего логина пароль не
        проверяется, и ответ приходит в десятки раз быстрее. По времени
        ответа можно узнать, какие логины есть, и бить только по ним."""

        def timing(username):
            samples = []
            for _ in range(5):
                limiter.failures.clear()
                started = time.perf_counter()
                self.wrong_login(username)
                samples.append(time.perf_counter() - started)
            return statistics.median(samples)

        existing, missing = timing("admin"), timing("no-such-user-42")
        self.assertLess(
            existing / missing, 3,
            f"существующий логин: {existing * 1000:.0f} мс, "
            f"несуществующий: {missing * 1000:.0f} мс",
        )

    def test_unauthenticated_requests_do_not_write_to_database(self):
        """УЯЗВИМОСТЬ, если падает: любой человек из интернета без входа
        может бесконечно добавлять строки в таблицу errors (кривой запрос
        на /api/auth/login), раздувая базу и диск сервера."""
        anonymous = self.client_for()
        before = len(self.errors())
        for _ in range(20):
            anonymous.post("/api/auth/login", content=b"{", headers={"Content-Type": "application/json"})
            anonymous.post("/api/auth/login", json={"nope": 1})
        for _ in range(limiter.MAX_FAILURES + 5):
            self.wrong_login("admin", client=anonymous)  # 429 тоже пишется
        self.assertEqual(len(self.errors()) - before, 0, "анонимные запросы записаны в базу")


# ---------- SQL-инъекции ----------

class SqlInjectionTest(ApiTestCase):

    PAYLOADS = [
        "' OR '1'='1",
        "'; DROP TABLE products; --",
        "\" OR 1=1 --",
        "x') UNION SELECT name, sql, 1, 1, 1, 1, 1, 1, 1 FROM sqlite_master --",
        "%' OR 1=1 --",
    ]

    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)
        self.login("admin")

    def assert_database_intact(self):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            tables = {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT COUNT(*) FROM products")
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assertTrue({"products", "fridge", "freezer", "users", "accounts"} <= tables)

    def test_search_fields(self):
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                for url, params in (
                    ("/api/admin/tables/products", {"q": payload}),
                    ("/api/admin/tables/users", {"q": payload}),
                    ("/api/admin/logs/operations", {"q": payload, "type": payload,
                                                    "date_from": payload}),
                    ("/api/admin/logs/changes", {"q": payload}),
                ):
                    response = self.client.get(url, params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertNotIn("CREATE TABLE", response.text)
                    self.assertEqual(response.json()["total"], 0, url)
                # Неизвестный тип операции просто не фильтрует список.
                everything = self.client.get("/api/history").json()["total"]
                response = self.client.get("/api/history", params={"type": payload})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["total"], everything)
        self.assert_database_intact()

    def test_sort_column_and_table_name(self):
        for payload in self.PAYLOADS + ["name; DROP TABLE products", "rowid", "(SELECT 1)"]:
            with self.subTest(payload=payload):
                response = self.client.get(
                    "/api/admin/tables/products", params={"sort": payload}
                )
                self.assertEqual(response.status_code, 200)
                response = self.client.get(f"/api/admin/tables/{payload}")
                self.assertIn(response.status_code, (404, 405))
        for table in ("accounts", "sqlite_master", "change_log", "daily_notifications"):
            self.assertEqual(self.client.get(f"/api/admin/tables/{table}").status_code, 404)
        self.assert_database_intact()

    def test_values_are_stored_as_text(self):
        """Инъекция в данных сохраняется как обычный текст."""
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post("/api/admin/products", json={
                    "name": payload[:60], "fridge_storage_time": 2,
                })
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["name"], " ".join(payload[:60].split()))
        response = self.client.post("/api/admin/tables/operations/rows", json={"values": {
            "operation_type": "sale", "product_name": self.PAYLOADS[1], "quantity": 1,
            "created_at": "2026-01-01 10:00", "created_by": 1,
            "reason": "x'); DELETE FROM users; --",
        }})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.accounts.users()), 2)
        with self.db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM products")
            self.assertEqual(cursor.fetchone()[0], 1 + len(self.PAYLOADS))

    def test_column_names_from_request_are_not_trusted(self):
        for values in (
            {'name" = \'hacked\' --': "x"},
            {"name": "x", "rowid": 1},
            {"__rowid": 5},
        ):
            with self.subTest(values=values):
                response = self.client.patch(
                    "/api/admin/tables/products/rows/1", json={"values": values}
                )
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.db.get_product_by_id(1)["name"], "Медовик")


# ---------- Файлы: обход путей ----------

class PathTraversalTest(ApiTestCase):

    def setUp(self):
        super().setUp()
        dist = self.temp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        (self.temp_path / "secret_key").write_text("SECRET", encoding="utf-8")
        self.app = create_app({
            **self.app.state.settings, "frontend_dist": str(dist),
        })
        self.db = self.app.state.db
        self.client = self.client_for()

    def test_frontend_does_not_serve_files_outside_dist(self):
        for path in (
            "/../test.db", "/..%2ftest.db", "/%2e%2e/test.db", "/..%5ctest.db",
            "/assets/../../test.db", "/assets/..%2f..%2ftest.db", "/....//test.db",
            "/..%2fsecret_key", "/%2e%2e%2f%2e%2e%2fsecret_key",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertNotIn(b"SQLite format", response.content)
                self.assertNotIn(b"SECRET", response.content)

    def test_backup_names_cannot_escape_folder(self):
        self.login("admin")
        self.client.post("/api/admin/backups")
        for name in ("..%2Ftest.db", "../test.db", "..%5Ctest.db", "....db", "%2e%2e%2ftest.db"):
            for method in ("GET", "DELETE"):
                with self.subTest(name=name, method=method):
                    response = self.client.request(method, f"/api/admin/backups/{name}")
                    self.assertNotEqual(response.status_code, 200)
                    self.assertNotIn(b"SQLite format", response.content)
        self.assertTrue((self.temp_path / "test.db").is_file())

    def test_restore_rejects_traversal(self):
        self.login("admin")
        response = self.client.post("/api/admin/backups/..%2Ftest.db/restore")
        self.assertNotEqual(response.status_code, 200)


# ---------- Целостность данных ----------

class DataIntegrityTest(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 10)
        self.batch_id = self.db.move_to_fridge("Медовик", 5)["id"]
        self.login("employee")

    def operations_sum(self, operation_type):
        with self.db.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM operations WHERE operation_type = ?",
                (operation_type,),
            )
            return cursor.fetchone()[0]

    def test_bad_quantities_are_rejected(self):
        bad = [0, -1, -100, 10**6, 10**30, 2**63, "1; DROP TABLE fridge", 1.5, None, [], "∞"]
        for quantity in bad:
            with self.subTest(quantity=quantity):
                for path, body in (
                    (f"/api/batches/{self.batch_id}/sale", {"quantity": quantity}),
                    (f"/api/batches/{self.batch_id}/write-off",
                     {"reason": "expired", "quantity": quantity}),
                    ("/api/defrost", {"product_id": 1, "quantity": quantity}),
                    ("/api/delivery", {"product_id": 1, "quantity": quantity}),
                ):
                    response = self.client.post(path, json=body)
                    self.assertIn(response.status_code, (400, 422), f"{path}: {response.text}")
        self.assertEqual(self.db.get_fridge_batch(self.batch_id)["quantity"], 5)
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 5)

    def test_cannot_sell_more_than_in_batch(self):
        response = self.client.post(f"/api/batches/{self.batch_id}/sale", json={"quantity": 6})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.operations_sum("sale"), 0)

    def test_write_off_reason_is_limited(self):
        response = self.client.post(f"/api/batches/{self.batch_id}/write-off", json={
            "reason": "other", "reason_text": "x" * 10_000, "quantity": 1,
        })
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/batches/{self.batch_id}/write-off", json={
            "reason": "<script>", "quantity": 1,
        })
        self.assertEqual(response.status_code, 400)

    def test_huge_ids_and_pages_do_not_crash_server(self):
        """Огромные номера не должны вызывать ошибку 500 (и запись в errors)."""
        for method, path, body in (
            ("GET", "/api/history?page=99999999999999999999", None),
            ("GET", f"/api/batches/{2**70}", None),
            ("POST", "/api/defrost", {"product_id": 2**70, "quantity": 1}),
            ("POST", f"/api/batches/{2**70}/sale", {"quantity": 1}),
        ):
            with self.subTest(path=path):
                response = self.client.request(method, path, json=body)
                self.assertLess(response.status_code, 500, response.text)

    def test_concurrent_sales_cannot_oversell_batch(self):
        """УЯЗВИМОСТЬ, если падает: проверка остатка и списание идут в
        разных шагах без блокировки. Два одновременных запроса (два
        планшета или скрипт) оба видят «в партии 5» и оба продают по 5 —
        в журнале 10 проданных из 5, остатки расходятся с реальностью."""
        original = Database._operation_details
        barrier = threading.Barrier(2)

        def slow_details(*args, **kwargs):
            # Оба запроса уже прочитали остаток; ждём друг друга.
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass
            return original(*args, **kwargs)

        clients = [self.client_for(), self.client_for()]
        for client in clients:
            self.login("employee", client=client)
        results = []

        def sell(client):
            results.append(client.post(
                f"/api/batches/{self.batch_id}/sale", json={"quantity": 5}
            ).status_code)

        with mock.patch.object(Database, "_operation_details", staticmethod(slow_details)):
            threads = [threading.Thread(target=sell, args=(client,)) for client in clients]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        self.assertLessEqual(
            self.operations_sum("sale"), 5,
            f"из партии в 5 шт. продано {self.operations_sum('sale')} (ответы {results})",
        )

    def test_concurrent_defrost_cannot_create_stock(self):
        """УЯЗВИМОСТЬ, если падает: то же при разморозке — из 5 шт. в
        морозильнике в холодильнике появляется 10."""
        original = Database._add_fridge_batch
        barrier = threading.Barrier(2)

        def slow_add(self_db, cursor, product_name, quantity):
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass
            return original(self_db, cursor, product_name, quantity)

        errors = []

        def defrost():
            try:
                self.db.move_to_fridge("Медовик", 5)
            except Exception as error:
                errors.append(error)

        with mock.patch.object(Database, "_add_fridge_batch", slow_add):
            threads = [threading.Thread(target=defrost) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        with self.db.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM fridge")
            in_fridge = cursor.fetchone()[0]
        self.assertLessEqual(
            in_fridge, 10, f"в холодильнике {in_fridge} шт., а всего было 10 (ошибки: {errors})"
        )


# ---------- Утечки информации и заголовки ----------

class InformationLeakTest(ApiTestCase):

    def test_server_error_hides_details(self):
        self.login("admin")
        with mock.patch("storage.queries.stats", side_effect=RuntimeError("SECRET /home/x/db")):
            response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("SECRET", response.text)
        self.assertNotIn("Traceback", response.text)

    def test_api_docs_are_not_public(self):
        """Схема API (все адреса и поля) не должна быть видна без входа."""
        anonymous = self.client_for()
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                response = anonymous.get(path)
                self.assertFalse("/api/admin" in response.text, f"{path} открыт всем")

    def test_security_headers(self):
        """Защитные заголовки: запрет показа сайта во фрейме чужого сайта
        (кликджекинг) и угадывания типа файлов браузером."""
        response = self.client.get("/")
        headers = {key.lower(): value for key, value in response.headers.items()}
        with self.subTest("X-Content-Type-Options"):
            self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        with self.subTest("X-Frame-Options / frame-ancestors"):
            self.assertTrue(
                "x-frame-options" in headers
                or "frame-ancestors" in headers.get("content-security-policy", ""),
                "нет запрета на встраивание во фрейм",
            )

    def test_server_log_and_errors_are_admin_only(self):
        self.login("employee")
        for path in ("/api/admin/logs/server", "/api/admin/logs/errors",
                     "/api/admin/backups", "/api/admin/google"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)


# ---------- Настройки для сервера ----------

class DeploymentConfigTest(ApiTestCase):

    def test_example_config_is_safe_for_vps(self):
        """На VPS сайт должен слушать только 127.0.0.1 за nginx/Caddy с
        HTTPS, а cookie — уходить только по HTTPS. В .env.example сейчас
        HOST=0.0.0.0 (сайт открыт всему интернету по HTTP: пароли и
        cookie передаются открытым текстом) и SECURE_COOKIES пусто."""
        example = Path(__file__).resolve().parent.parent / ".env.example"
        settings = dict(
            line.split("=", 1) for line in example.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
        with self.subTest("HOST"):
            self.assertEqual(settings.get("HOST", "").strip(), "127.0.0.1")
        with self.subTest("SECURE_COOKIES"):
            self.assertEqual(settings.get("SECURE_COOKIES", "").strip(), "1")

    def test_generated_secret_key_is_strong(self):
        from api import load_secret_key
        key = load_secret_key(self.temp_path / "new" / "secret_key")
        self.assertGreaterEqual(len(key), 64)
        self.assertEqual(load_secret_key(self.temp_path / "new" / "secret_key"), key)
