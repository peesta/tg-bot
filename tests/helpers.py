"""Общие заготовки для тестов.

BotTestCase — бот с временной базой. Запросы к Telegram никуда не уходят,
а записываются, и тест проверяет, что бот ответил.

FakeSheetsServer — Google Sheets API в памяти. Через fake_spreadsheet()
с ним работает настоящий gspread, так что проверяются и вызовы библиотеки.
"""
import itertools
import logging
import re
import tempfile
import unittest
from datetime import datetime
from json import dumps as json_dumps
from pathlib import Path
from urllib.parse import unquote

import gspread
import requests
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import (
    AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod,
)
from aiogram.types import Chat, Message
from gspread.http_client import HTTPClient

from storage.db import Database
from telegram.handler import router
from telegram.utils import today


ADMIN_ID = 1  # владелец из ADMIN_IDS, его нет в таблице users
ERROR_TEXT = "Что-то пошло не так"


# ---------- Бот без Telegram ----------

class FakeSession(BaseSession):
    """Сессия aiogram, которая записывает запросы вместо отправки."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.blocked_users: set[int] = set()
        self._message_ids = itertools.count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            if method.chat_id in self.blocked_users:
                raise TelegramForbiddenError(
                    method=method, message="Forbidden: bot was blocked by the user"
                )
            return Message(
                message_id=next(self._message_ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


class BotSimulator:
    """Отправляет боту сообщения и нажатия кнопок от имени пользователей."""

    def __init__(self, db: Database, **workflow_data) -> None:
        self.session = FakeSession()
        self.bot = Bot(
            "123456:TEST",
            session=self.session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        # Роутер из telegram.handler один на модуль, а диспетчер в каждом
        # тесте новый: отвязываем роутер от диспетчера прошлого теста.
        router._parent_router = None
        self.dispatcher = Dispatcher(db=db, **workflow_data)
        self.dispatcher.include_router(router)
        self._update_ids = itertools.count(1)

    @staticmethod
    def user(user_id: int) -> dict:
        return {"id": user_id, "is_bot": False, "first_name": f"User{user_id}"}

    async def feed(self, update: dict) -> list[TelegramMethod]:
        """Обрабатывает update и возвращает запросы, которые сделал бот."""
        start = len(self.session.requests)
        update = {"update_id": next(self._update_ids), **update}
        await self.dispatcher.feed_raw_update(self.bot, update)
        return self.session.requests[start:]

    async def send(self, user_id: int, text: str) -> list[TelegramMethod]:
        message = {
            "message_id": 1,
            "date": int(datetime.now().timestamp()),
            "chat": {"id": user_id, "type": "private"},
            "from": self.user(user_id),
            "text": text,
        }
        if text.startswith("/"):
            command_length = len(text.split()[0])
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": command_length}
            ]
        return await self.feed({"message": message})

    async def click(self, user_id: int, data: str) -> list[TelegramMethod]:
        return await self.feed({"callback_query": {
            "id": "1",
            "from": self.user(user_id),
            "chat_instance": "test",
            "data": data,
            "message": {
                "message_id": 500,
                "date": int(datetime.now().timestamp()),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 123456, "is_bot": True, "first_name": "Bot"},
                "text": "старое сообщение",
            },
        }})


def texts(requests: list[TelegramMethod]) -> list[str]:
    """Тексты отправленных и изменённых сообщений."""
    return [
        request.text for request in requests
        if isinstance(request, (SendMessage, EditMessageText))
    ]


def last_text(requests: list[TelegramMethod]) -> str:
    all_texts = texts(requests)
    return all_texts[-1] if all_texts else ""


def alerts(requests: list[TelegramMethod]) -> list[str]:
    """Всплывающие уведомления после нажатия кнопки."""
    return [
        request.text for request in requests
        if isinstance(request, AnswerCallbackQuery) and request.text
    ]


def last_markup(requests: list[TelegramMethod]):
    for request in reversed(requests):
        if isinstance(request, (SendMessage, EditMessageText)):
            return request.reply_markup
    return None


def callbacks(requests: list[TelegramMethod]) -> list[str]:
    """callback_data кнопок последнего сообщения."""
    markup = last_markup(requests)
    if markup is None:
        return []
    return [
        button.callback_data
        for row in markup.inline_keyboard for button in row
        if button.callback_data
    ]


def sent_to(requests: list[TelegramMethod], user_id: int) -> list[str]:
    """Тексты новых сообщений, отправленных пользователю."""
    return [
        request.text for request in requests
        if isinstance(request, SendMessage) and request.chat_id == user_id
    ]


class TempDatabaseTestCase(unittest.TestCase):
    """База данных во временной папке, удаляется после теста."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db = Database(str(self.temp_path / "test.db"))


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    """Бот с временной базой и владельцем ADMIN_ID."""

    def setUp(self) -> None:
        # Ошибки, которые тесты вызывают нарочно, не засоряют вывод.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db = Database(str(self.temp_path / "test.db"))
        self.telegram = BotSimulator(
            self.db, admin_ids=frozenset({ADMIN_ID}), **self.workflow_data()
        )

    def workflow_data(self) -> dict:
        """Дополнительные данные для обработчиков (например, google_table)."""
        return {}

    async def send(self, user_id: int, text: str) -> list[TelegramMethod]:
        return await self.telegram.send(user_id, text)

    async def click(self, user_id: int, data: str) -> list[TelegramMethod]:
        return await self.telegram.click(user_id, data)

    def assertNoBotError(self, requests: list[TelegramMethod]) -> None:
        for text in texts(requests):
            self.assertNotIn(ERROR_TEXT, text)

    def skip_daily_notification(self, *user_ids: int) -> None:
        """Отмечает, что сегодня уведомление уже было: оно не помешает проверкам."""
        for user_id in user_ids:
            self.db.mark_daily_notification(user_id, today())

    def set_expiration(self, batch_id: int, days_from_today: int) -> None:
        """Сдвигает срок годности партии относительно сегодняшнего дня."""
        with self.db.cursor() as cursor:
            cursor.execute(
                "UPDATE fridge SET expiration_date = date('now', 'localtime', ?) "
                "WHERE id = ?",
                (f"{days_from_today} day", batch_id),
            )


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

