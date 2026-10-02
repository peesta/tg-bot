"""Экспорт и импорт Google Таблицы.

Сеть не используется: настоящий gspread работает с FakeSheetsServer.
"""
import json
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth.exceptions import RefreshError, TransportError

import storage.google_sheets as google_sheets
from storage.db import Database
from storage.google_sheets import GoogleSheetsError, ImportDataError
from tests.helpers import (
    ADMIN_ID, BotTestCase, FakeSheetsServer, TempDatabaseTestCase, alerts,
    callbacks, fake_spreadsheet, last_markup, last_text, texts,
)


HEADERS = {
    "products": ["name", "fridge_storage_time", "freezer_storage_time", "category"],
    "freezer": ["product_name", "quantity"],
    "fridge": ["id", "product_name", "quantity", "date_added", "expiration_date"],
}
TABLE_URL = "https://docs.google.com/spreadsheets/d/KEY/edit"
REAL_OPEN_SPREADSHEET = google_sheets.open_spreadsheet


def import_errors(sheets) -> list[str]:
    try:
        google_sheets.parse_tables(sheets)
    except ImportDataError as error:
        return error.errors
    return []


class ParseTablesTest(unittest.TestCase):
    def test_all_errors_with_row_numbers(self):
        errors = import_errors({
            "products": [
                HEADERS["products"], ["Медовик", "3"], ["медовик", "2"],
                ["", "2"], ["Лосось", "0"], ["Мотти", "abc", "-1"],
            ],
            "freezer": [
                HEADERS["freezer"], ["Медовик", "2"], ["Медовик", "1"],
                ["Чизкейк", "1"], ["Лосось", "0"],
            ],
            "fridge": [
                HEADERS["fridge"],
                ["1", "Медовик", "1", "2026-10-01", "2026-10-03"],
                ["1", "Медовик", "1", "", "2026-10-03"],
                ["x", "", "-3", "32.13.2026", "10/05/2026"],
                ["", "Медовик", "1", "2026-10-05", "2026-10-01"],
            ],
        })
        self.assertTrue(all("строка" in error for error in errors))
        expected_parts = [
            "products, строка 3: товар «медовик» уже есть в строке 2",
            "products, строка 4: не указано название",
            "products, строка 5: fridge_storage_time",
            "products, строка 6: freezer_storage_time",
            "freezer, строка 3: товар «Медовик» уже есть в строке 2",
            "freezer, строка 4: товара «Чизкейк» нет на листе products",
            "freezer, строка 5: quantity",
            "fridge, строка 3: партия с id 1 уже есть в строке 2",
            "fridge, строка 4: id",
            "fridge, строка 4: date_added",
            "fridge, строка 4: expiration_date",
            "fridge, строка 5: срок годности раньше даты добавления",
        ]
        for part in expected_parts:
            self.assertTrue(any(part in error for error in errors), part)

    def test_missing_column_and_empty_sheet(self):
        sheets = {"products": [["name"], ["Медовик"]], "freezer": [HEADERS["freezer"]], "fridge": [HEADERS["fridge"]]}
        self.assertEqual(import_errors(sheets), ["products: нет столбцов fridge_storage_time."])
        sheets["products"] = []
        self.assertIn("лист пуст", import_errors(sheets)[0])

    def test_column_order_case_and_extra_columns(self):
        tables = google_sheets.parse_tables({
            "products": [["Комментарий", "FRIDGE_STORAGE_TIME", "Name"], ["x", "2", "Медовик"]],
            "freezer": [["quantity", "product_name"], ["1 000", "Медовик"]],
            "fridge": [["expiration_date", "quantity", "product_name"], ["05.10.2026", "5.0", " Медовик "]],
        })
        self.assertEqual(tables["products"][0]["fridge_storage_time"], 2)
        self.assertEqual(tables["freezer"], [{"product_name": "Медовик", "quantity": 1000}])
        batch = tables["fridge"][0]
        self.assertEqual((batch["id"], batch["quantity"], batch["expiration_date"]), (None, 5, "2026-10-05"))

    def test_headers_only_means_empty_tables(self):
        self.assertEqual(
            google_sheets.parse_tables({title: [header] for title, header in HEADERS.items()}),
            {"products": [], "freezer": [], "fridge": []},
        )


class ExportImportTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        for name, days in (("Филадельфия", 2), ("Медовик", 3), ("=SUM(A1:A2)", 1), ("Калифорния", 1)):
            self.db.new_product(name, days)
        for name, quantity in (("Филадельфия", 10), ("Медовик", 4), ("=SUM(A1:A2)", 2)):
            self.db.new_delivery(name, quantity)
        self.db.move_to_fridge("Филадельфия", 3)
        self.db.move_to_fridge("Медовик", 1)
        self.server = FakeSheetsServer()

    def export(self, server=None, db=None):
        return google_sheets.write_tables(fake_spreadsheet(server or self.server), (db or self.db).stock_tables())

    def import_(self):
        self.db.replace_stock_tables(**google_sheets.parse_tables(
            google_sheets.read_tables(fake_spreadsheet(self.server))
        ))

    def test_export(self):
        self.server = FakeSheetsServer(titles=("freezer", "products", "Заметки"))
        self.server.set_values("freezer", [["мусор"] * 3] * 50)
        self.server.set_values("Заметки", [["не трогать"]])

        self.assertEqual(self.export(), {"products": 4, "freezer": 3, "fridge": 2})

        self.assertIn("fridge", self.server.sheets)  # лист создан
        self.assertEqual(len(self.server.values("freezer")), 4)  # старое стёрто
        self.assertEqual(self.server.values("Заметки"), [["не трогать"]])
        self.assertEqual(self.server.values("products")[0], HEADERS["products"])
        self.assertIn(["=SUM(A1:A2)", 1, "", ""], self.server.values("products"))
        for title in HEADERS:
            self.assertTrue(self.server.sheets[title]["bold"])
            self.assertEqual(self.server.sheets[title]["frozen"], 1)

    def test_export_resizes_small_sheets(self):
        small = FakeSheetsServer(rows=1, cols=1)
        self.export(server=small)
        self.assertGreaterEqual(small.sheets["fridge"]["cols"], 5)
        self.assertEqual(len(small.values("products")), 5)

        empty_db = Database(str(self.temp_path / "empty.db"))
        self.assertEqual(self.export(server=FakeSheetsServer(rows=1, cols=1), db=empty_db),
                         {"products": 0, "freezer": 0, "fridge": 0})

    def test_export_then_import_changes_nothing(self):
        before = self.db.stock_tables()
        ids_before = [p["id"] for p in self.db.products_list(1, 100)[1]]
        self.export()
        self.import_()
        self.assertEqual(self.db.stock_tables(), before)
        self.assertEqual([p["id"] for p in self.db.products_list(1, 100)[1]], ids_before)

    def test_import_edits_made_in_table(self):
        self.export()
        products = [row for row in self.server.values("products") if row[0] != "Калифорния"]
        self.server.set_values("products", products + [["  Новый   ролл ", "2", "", "Роллы"]])
        self.server.set_values("freezer", self.server.values("freezer") + [["Новый ролл", "1 000"]])
        self.server.set_values("fridge", self.server.values("fridge") + [
            ["", "Новый ролл", "5.0", "", "05.10.2026"], ["", "", "", "", ""],
        ])

        self.import_()

        tables = self.db.stock_tables()
        self.assertNotIn("Калифорния", [p["name"] for p in tables["products"]])
        new_product = [p for p in tables["products"] if p["name"] == "Новый ролл"][0]
        self.assertEqual(new_product["category"], "Роллы")
        self.assertEqual(self.db.get_freezer_product("Новый ролл")["quantity"], 1000)
        new_batch = [b for b in tables["fridge"] if b["product_name"] == "Новый ролл"][0]
        self.assertEqual(new_batch["expiration_date"], "2026-10-05")
        self.assertEqual(self.db.move_to_fridge("Новый ролл", 1)["quantity"], 1)

    def test_import_with_errors_changes_nothing(self):
        before = self.db.stock_tables()
        self.server.set_values("products", [HEADERS["products"], ["Медовик", "0"]])
        self.server.set_values("freezer", [HEADERS["freezer"]])
        self.server.set_values("fridge", [HEADERS["fridge"]])

        with mock.patch.object(google_sheets, "open_spreadsheet", return_value=fake_spreadsheet(self.server)):
            with self.assertRaises(ImportDataError):
                google_sheets.import_from_google(self.db, "KEY")

        self.assertEqual(self.db.stock_tables(), before)
        self.assertFalse((self.temp_path / "backups").exists())

    def test_import_saves_backup(self):
        before = self.db.stock_tables()
        self.server.set_values("products", [HEADERS["products"], ["Медовик", "4"]])
        self.server.set_values("freezer", [HEADERS["freezer"], ["Медовик", "7"]])
        self.server.set_values("fridge", [HEADERS["fridge"]])

        with mock.patch.object(google_sheets, "open_spreadsheet", return_value=fake_spreadsheet(self.server)):
            counts, backup_path = google_sheets.import_from_google(self.db, "KEY")

        self.assertEqual(counts, {"products": 1, "freezer": 1, "fridge": 0})
        self.assertEqual(Database(backup_path).stock_tables(), before)
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 7)

    def test_missing_sheet(self):
        del self.server.sheets["fridge"]
        with self.assertRaises(ImportDataError) as caught:
            google_sheets.read_tables(fake_spreadsheet(self.server))
        self.assertEqual(caught.exception.errors, ["В таблице нет листа «fridge»."])

    def test_google_error_during_export(self):
        spreadsheet = fake_spreadsheet(self.server)
        self.server.fail = (500, "Internal error")
        with mock.patch.object(google_sheets, "open_spreadsheet", return_value=spreadsheet):
            with self.assertRaises(GoogleSheetsError) as caught:
                google_sheets.export_to_google(self.db, "KEY")
        self.assertIn("Google вернул ошибку", str(caught.exception))


class OpenSpreadsheetTest(TempDatabaseTestCase):
    def setUp(self):
        super().setUp()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.credentials = str(self.temp_path / "credentials.json")
        self.write_json(self.credentials, {
            "type": "service_account", "project_id": "test", "private_key_id": "1",
            "private_key": pem, "client_email": "bot@test.iam.gserviceaccount.com",
            "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token",
        })

    @staticmethod
    def write_json(path, data):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file)

    def error_text(self, table, credentials=None) -> str:
        with self.assertRaises(GoogleSheetsError) as caught:
            google_sheets.open_spreadsheet(table, credentials or self.credentials)
        return str(caught.exception)

    def test_no_table(self):
        self.assertIn("GOOGLE_TABLE", self.error_text(None))

    def test_no_credentials_file(self):
        self.assertIn("Нет файла", self.error_text("KEY", str(self.temp_path / "nope.json")))

    def test_wrong_credentials_file(self):
        oauth_client = str(self.temp_path / "oauth.json")
        self.write_json(oauth_client, {"installed": {"client_id": "x"}})
        self.assertIn("не похож на ключ сервисного аккаунта", self.error_text("KEY", oauth_client))

        broken = self.temp_path / "broken.json"
        broken.write_text("{не json", encoding="utf-8")
        self.assertIn("не похож на ключ сервисного аккаунта", self.error_text("KEY", str(broken)))

    def test_bad_link(self):
        self.assertIn("ID таблицы", self.error_text("https://docs.google.com/document/xyz"))

    def test_no_access(self):
        server = FakeSheetsServer()
        for status, message in ((403, "The caller does not have permission"), (404, "Not found")):
            server.fail = (status, message)
            with self.assertRaises(GoogleSheetsError) as caught:
                with google_sheets._google_errors(self.credentials):
                    fake_spreadsheet(server)
            self.assertIn("bot@test.iam.gserviceaccount.com", str(caught.exception))
            self.assertIn(message, str(caught.exception))

    def test_revoked_key_and_network(self):
        for error, expected in ((RefreshError("invalid_grant"), "не принял ключ"),
                                (TransportError("timeout"), "Не удалось связаться")):
            with self.assertRaises(GoogleSheetsError) as caught:
                with google_sheets._google_errors(self.credentials):
                    raise error
            self.assertIn(expected, str(caught.exception))

    def test_spreadsheet_url(self):
        self.assertEqual(google_sheets.spreadsheet_url("KEY"), TABLE_URL)
        self.assertEqual(google_sheets.spreadsheet_url(TABLE_URL), TABLE_URL)


class GoogleSheetsButtonsTest(BotTestCase):
    def workflow_data(self):
        return {"google_table": TABLE_URL}

    def setUp(self):
        super().setUp()
        self.db.add_user(555, "Иван")
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)
        self.server = FakeSheetsServer()
        patcher = mock.patch.object(
            google_sheets, "open_spreadsheet",
            side_effect=lambda *args, **kwargs: fake_spreadsheet(self.server),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_buttons_for_admin_only(self):
        requests = await self.click(ADMIN_ID, "settings")
        self.assertIn("gsheet_export", callbacks(requests))
        self.assertIn("gsheet_import", callbacks(requests))

        for data in ("gsheet_export", "gsheet_export_yes", "gsheet_import_yes"):
            requests = await self.click(555, data)
            self.assertEqual(texts(requests), [])
            self.assertIn("устарела", alerts(requests)[0])

    async def test_export(self):
        self.assertIn("gsheet_export_yes", callbacks(await self.click(ADMIN_ID, "gsheet_export")))
        requests = await self.click(ADMIN_ID, "gsheet_export_yes")

        kinds = [type(request).__name__ for request in requests]
        self.assertLess(kinds.index("AnswerCallbackQuery"), kinds.index("EditMessageText"))
        self.assertIn("Выгружаю", texts(requests)[0])
        self.assertIn("Экспорт завершён", last_text(requests))
        links = [button.url for row in last_markup(requests).inline_keyboard for button in row]
        self.assertIn(TABLE_URL, links)
        self.assertEqual(self.server.values("freezer")[1], ["Медовик", 5])

    async def test_import_with_errors(self):
        self.server.set_values("products", [HEADERS["products"], ["Медовик", "3"]])
        self.server.set_values("freezer", [HEADERS["freezer"], ["Чизкейк", "ноль"]])
        self.server.set_values("fridge", [HEADERS["fridge"]])

        requests = await self.click(ADMIN_ID, "gsheet_import_yes")

        self.assertIn("база не изменена", last_text(requests))
        self.assertIn("Чизкейк", last_text(requests))
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 5)

    async def test_import(self):
        self.server.set_values("products", [HEADERS["products"], ["Медовик", "3"]])
        self.server.set_values("freezer", [HEADERS["freezer"], ["Медовик", "9"]])
        self.server.set_values("fridge", [HEADERS["fridge"]])

        requests = await self.click(ADMIN_ID, "gsheet_import_yes")

        self.assertIn("Импорт завершён", last_text(requests))
        self.assertIn("before_import_", last_text(requests))
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 9)

    async def test_no_parallel_runs(self):
        from telegram.handlers.google_sheets import sync_lock

        await sync_lock.acquire()
        try:
            requests = await self.click(ADMIN_ID, "gsheet_import_yes")
        finally:
            sync_lock.release()
        self.assertIn("Уже идёт", last_text(requests))

    async def test_google_error(self):
        spreadsheet = fake_spreadsheet(self.server)  # таблица открылась, сбой позже
        self.server.fail = (429, "Quota exceeded")
        with mock.patch.object(google_sheets, "open_spreadsheet", return_value=spreadsheet):
            requests = await self.click(ADMIN_ID, "gsheet_export_yes")
        self.assertIn("Экспорт не выполнен", last_text(requests))
        self.assertIn("Quota exceeded", last_text(requests))

    async def test_no_google_table(self):
        self.telegram.dispatcher["google_table"] = None
        with mock.patch.object(google_sheets, "open_spreadsheet", REAL_OPEN_SPREADSHEET):
            requests = await self.click(ADMIN_ID, "gsheet_export_yes")
        self.assertIn("GOOGLE_TABLE", last_text(requests))


if __name__ == "__main__":
    unittest.main()
