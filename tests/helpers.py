"""Общие заготовки для тестов.

ApiTestCase — сайт с временной базой и тестовым клиентом FastAPI.

FakeSheetsServer — Google Sheets API в памяти. Через fake_spreadsheet()
с ним работает настоящий gspread, так что проверяются и вызовы библиотеки.
"""
import itertools
import logging
import re
import tempfile
import unittest
import warnings
from json import dumps as json_dumps
from pathlib import Path
from urllib.parse import unquote

import gspread
import requests
from gspread.http_client import HTTPClient

from storage.db import Database

with warnings.catch_warnings():
    # Starlette советует httpx2, тестовому клиенту хватает httpx.
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from api import create_app
from api.auth import limiter


TABLE_URL = "https://docs.google.com/spreadsheets/d/KEY/edit"
# Без этого заголовка сервер не принимает изменения (защита от чужих сайтов).
HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def set_expiration(db: Database, batch_id: int, days_from_today: int) -> None:
    """Сдвигает срок годности партии относительно сегодняшнего дня."""
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE fridge SET expiration_date = date('now', 'localtime', ?) "
            "WHERE id = ?",
            (f"{days_from_today} day", batch_id),
        )


class TempDatabaseTestCase(unittest.TestCase):
    """База данных во временной папке, удаляется после теста."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db = Database(str(self.temp_path / "test.db"))


class ApiTestCase(unittest.TestCase):
    """Сайт с временной базой. Учётные записи admin/admin (№ 1) и
    employee/employee (№ 2) создаются автоматически, как при первом запуске."""

    ADMIN_ID = 1
    EMPLOYEE_ID = 2

    def setUp(self) -> None:
        # Ошибки, которые тесты вызывают нарочно, не засоряют вывод.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        limiter.failures.clear()
        self.addCleanup(limiter.failures.clear)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.app = create_app({
            "database": str(self.temp_path / "test.db"),
            "secret_key": "test",
            "log_file": str(self.temp_path / "app.log"),
            "credentials_file": str(self.temp_path / "credentials.json"),
            "google_table": TABLE_URL,
            "frontend_dist": str(self.temp_path / "dist"),
        })
        self.db: Database = self.app.state.db
        self.accounts = self.app.state.accounts
        self.client = self.client_for()

    def client_for(self) -> TestClient:
        """Отдельный браузер со своей сессией."""
        client = TestClient(self.app, raise_server_exceptions=False, headers=HEADERS)
        self.addCleanup(client.close)
        return client

    def login(self, username: str, password: str | None = None, client: TestClient | None = None):
        response = (client or self.client).post(
            "/api/auth/login", json={"username": username, "password": password or username}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def errors(self) -> list[dict]:
        with self.db.cursor() as cursor:
            cursor.execute("SELECT * FROM errors ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def changes(self, action: str | None = None) -> list[dict]:
        with self.db.cursor() as cursor:
            cursor.execute("SELECT * FROM change_log ORDER BY id")
            rows = [dict(row) for row in cursor.fetchall()]
        return [row for row in rows if action is None or row["action"] == action]


# ---------- Google Таблица без Google ----------

class FakeSheetsServer:
    """Google Sheets API в памяти: одна таблица с ключом KEY."""

    KEY = "KEY"

    def __init__(self, titles=("Холодильник", "Морозильник", "Товары"), rows=1000, cols=26):
        self.sheets: dict[str, dict] = {}
        self._sheet_ids = itertools.count(1)
        self.fail: tuple[int, str] | None = None  # ответить ошибкой на всё
        for title in titles:
            self.add_sheet(title, rows, cols)

    def add_sheet(self, title: str, rows: int, cols: int) -> None:
        self.sheets[title] = {
            "id": next(self._sheet_ids), "rows": rows, "cols": cols,
            "values": [], "frozen": 0, "bold": False,
        }

    def values(self, title: str) -> list[list]:
        return self.sheets[title]["values"]

    def set_values(self, title: str, values: list[list]) -> None:
        self.sheets[title]["values"] = [list(row) for row in values]

    def _title_by_id(self, sheet_id: int) -> str:
        return next(t for t, s in self.sheets.items() if s["id"] == sheet_id)

    @staticmethod
    def _error(status: int, message: str) -> tuple[int, dict]:
        return status, {"error": {"code": status, "message": message, "status": "ERROR"}}

    def _metadata(self) -> dict:
        return {
            "spreadsheetId": self.KEY,
            "properties": {"title": "Test", "locale": "ru_RU"},
            "sheets": [
                {"properties": {
                    "sheetId": sheet["id"], "title": title, "index": index,
                    "sheetType": "GRID",
                    "gridProperties": {
                        "rowCount": sheet["rows"], "columnCount": sheet["cols"],
                        "frozenRowCount": sheet["frozen"],
                    },
                }}
                for index, (title, sheet) in enumerate(self.sheets.items())
            ],
        }

    def _batch_update(self, body: dict) -> tuple[int, dict]:
        replies = []
        for request in body["requests"]:
            if "addSheet" in request:
                properties = request["addSheet"]["properties"]
                grid = properties["gridProperties"]
                self.add_sheet(properties["title"], grid["rowCount"], grid["columnCount"])
                sheet = self.sheets[properties["title"]]
                replies.append({"addSheet": {"properties": {
                    "sheetId": sheet["id"], "title": properties["title"],
                    "index": len(self.sheets) - 1,
                    "gridProperties": {"rowCount": sheet["rows"], "columnCount": sheet["cols"]},
                }}})
            elif "updateSheetProperties" in request:
                properties = request["updateSheetProperties"]["properties"]
                old_title = self._title_by_id(properties["sheetId"])
                sheet = self.sheets[old_title]
                if "title" in properties:  # переименование, порядок листов тот же
                    self.sheets = {
                        (properties["title"] if title == old_title else title): value
                        for title, value in self.sheets.items()
                    }
                grid = properties.get("gridProperties", {})
                if "frozenRowCount" in grid:
                    if grid["frozenRowCount"] >= sheet["rows"]:
                        return self._error(400, "You can't freeze all visible rows on the sheet.")
                    sheet["frozen"] = grid["frozenRowCount"]
                sheet["rows"] = grid.get("rowCount", sheet["rows"])
                sheet["cols"] = grid.get("columnCount", sheet["cols"])
                replies.append({})
            elif "repeatCell" in request:
                sheet = self.sheets[self._title_by_id(request["repeatCell"]["range"]["sheetId"])]
                text_format = request["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]
                sheet["bold"] = text_format.get("bold", False)
                replies.append({})
            else:
                raise AssertionError(f"Неожиданный запрос: {request}")
        return 200, {"spreadsheetId": self.KEY, "replies": replies}

    def handle(self, method: str, url: str, params=None, json_body=None) -> tuple[int, dict]:
        if self.fail:
            return self._error(*self.fail)

        match = re.match(r"https://sheets\.googleapis\.com/v4/spreadsheets/([^/:]+)(.*)", url)
        if match is None:
            raise AssertionError(f"Неожиданный адрес: {url}")
        key, rest = match.group(1), unquote(match.group(2))
        if key != self.KEY:
            return self._error(404, "Requested entity was not found.")

        method = method.lower()
        if rest == "" and method == "get":
            return 200, self._metadata()
        if rest == ":batchUpdate":
            return self._batch_update(json_body)

        match = re.match(r"/values/(.+?)(?:!(.+?))?(:clear)?$", rest)
        if match is None:
            raise AssertionError(f"Неожиданный адрес: {url}")
        title = match.group(1).strip("'")
        sheet = self.sheets[title]

        if match.group(3):
            sheet["values"] = []
            return 200, {"spreadsheetId": key, "clearedRange": title}
        if method == "put":
            if (params or {}).get("valueInputOption") != "RAW":
                raise AssertionError("Значения должны записываться как RAW")
            values = json_body["values"]
            if len(values) > sheet["rows"]:
                return self._error(400, "Range exceeds grid limits.")
            sheet["values"] = [list(row) for row in values]
            return 200, {"spreadsheetId": key, "updatedRows": len(values)}
        if method == "get":
            # Как Google: все значения строками, пустые хвосты обрезаны.
            rows = [[str(value) for value in row] for row in sheet["values"]]
            rows = [self._trim(row) for row in rows]
            while rows and not rows[-1]:
                rows.pop()
            body = {"range": f"{title}!A1:Z{sheet['rows']}", "majorDimension": "ROWS"}
            if rows:
                body["values"] = rows
            return 200, body
        raise AssertionError(f"Неожиданный запрос: {method} {url}")

    @staticmethod
    def _trim(row: list[str]) -> list[str]:
        while row and row[-1] == "":
            row = row[:-1]
        return row


def fake_spreadsheet(server: FakeSheetsServer, key: str = FakeSheetsServer.KEY) -> gspread.Spreadsheet:
    """Настоящий gspread.Spreadsheet, который ходит в FakeSheetsServer."""

    class FakeHTTPClient(HTTPClient):
        def request(self, method, endpoint, params=None, data=None, json=None,
                    files=None, headers=None):
            status, body = server.handle(method, endpoint, params=params, json_body=json)
            response = requests.Response()
            response.status_code = status
            response._content = json_dumps(body).encode()
            response.headers["Content-Type"] = "application/json"
            if response.ok:
                return response
            raise gspread.exceptions.APIError(response)

    client = gspread.Client(auth=None, session=requests.Session(), http_client=FakeHTTPClient)
    return client.open_by_key(key)

