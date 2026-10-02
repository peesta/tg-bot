"""Общие заготовки для тестов.

WebTestCase — сайт с временной базой и тестовым клиентом Flask.

FakeSheetsServer — Google Sheets API в памяти. Через fake_spreadsheet()
с ним работает настоящий gspread, так что проверяются и вызовы библиотеки.
"""
import itertools
import logging
import re
import tempfile
import unittest
from json import dumps as json_dumps
from pathlib import Path
from urllib.parse import unquote

import gspread
import requests
from gspread.http_client import HTTPClient

from storage.db import Database
from web import create_app
from web.utils import today


ERROR_TEXT = "Что-то пошло не так"
TABLE_URL = "https://docs.google.com/spreadsheets/d/KEY/edit"


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


class WebTestCase(unittest.TestCase):
    """Сайт с временной базой. Учётные записи admin/admin и
    employee/employee создаются автоматически, как при первом запуске."""

    def setUp(self) -> None:
        # Ошибки, которые тесты вызывают нарочно, не засоряют вывод.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.app = create_app({
            "DATABASE": str(self.temp_path / "test.db"),
            "SECRET_KEY": "test",
            "LOG_FILE": str(self.temp_path / "app.log"),
            "CREDENTIALS_FILE": str(self.temp_path / "credentials.json"),
            "GOOGLE_TABLE": TABLE_URL,
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        })
        self.db: Database = self.app.extensions["db"]
        self.client = self.app.test_client()
        self.admin_id = self.db.get_user_by_username("admin")["id"]
        self.employee_id = self.db.get_user_by_username("employee")["id"]

    def csrf(self, client=None) -> str:
        with (client or self.client).session_transaction() as session:
            return session.setdefault("csrf_token", "test-csrf-token")

    def post(self, url: str, data: dict | None = None, client=None, **kwargs):
        """POST с CSRF-токеном из сессии, как у настоящей формы."""
        client = client or self.client
        data = {"csrf_token": self.csrf(client), **(data or {})}
        return client.post(url, data=data, **kwargs)

    def login(self, username: str, password: str | None = None, client=None):
        response = self.post(
            "/login",
            {"username": username, "password": password or username},
            client=client,
        )
        self.assertEqual(response.status_code, 302, response.text)
        return response

    def skip_daily_notice(self, *user_ids: int) -> None:
        """Отмечает, что сегодня уведомление уже было: оно не помешает проверкам."""
        for user_id in user_ids or (self.admin_id, self.employee_id):
            self.db.mark_daily_notification(user_id, today())

    @staticmethod
    def flashes(response) -> list[str]:
        """Тексты сообщений на странице (успех, ошибка, подсказка)."""
        return [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()
            for text in re.findall(
                r'<div class="alert[^"]*"[^>]*>(.*?)</div>', response.text, re.S
            )
        ]


# ---------- Google Таблица без Google ----------

class FakeSheetsServer:
    """Google Sheets API в памяти: одна таблица с ключом KEY."""

    KEY = "KEY"

    def __init__(self, titles=("fridge", "freezer", "products"), rows=1000, cols=26):
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
                sheet = self.sheets[self._title_by_id(properties["sheetId"])]
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

