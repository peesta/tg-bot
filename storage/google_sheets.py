"""Экспорт и импорт товаров, морозильника и холодильника в Google Таблицу.

В таблице три листа с названиями как у таблиц базы: products, freezer,
fridge. В первой строке листа — названия столбцов, как в базе.

Доступ — через сервисный аккаунт: ключ лежит в credentials.json, а самой
таблице дан доступ «Редактор» для почты сервисного аккаунта.

Функции здесь блокирующие (ходят в сеть), из асинхронного кода их нужно
вызывать через asyncio.to_thread.
"""
import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import gspread
from google.auth.exceptions import GoogleAuthError, TransportError
from requests.exceptions import RequestException

from storage.db import Database


CREDENTIALS_FILE = "credentials.json"

# Столбцы каждого листа в порядке выгрузки.
SHEET_COLUMNS = {
    "products": ("name", "fridge_storage_time", "freezer_storage_time", "category"),
    "freezer": ("product_name", "quantity"),
    "fridge": ("id", "product_name", "quantity", "date_added", "expiration_date"),
}
# Без этих столбцов лист не импортируется; остальные можно не заполнять.
REQUIRED_COLUMNS = {
    "products": ("name", "fridge_storage_time"),
    "freezer": ("product_name", "quantity"),
    "fridge": ("product_name", "quantity", "expiration_date"),
}

MAX_NUMBER = 1_000_000_000
DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y")


class GoogleSheetsError(Exception):
    """Ошибка, текст которой можно показать администратору."""


class ImportDataError(GoogleSheetsError):
    """Данные в таблице не прошли проверку, база не изменялась."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def spreadsheet_url(table: str) -> str:
    """Ссылка на таблицу по значению GOOGLE_TABLE (ссылка или ID)."""
    if table.startswith("http"):
        return table
    return f"https://docs.google.com/spreadsheets/d/{table}/edit"


def _service_account_email(credentials_file: str) -> str:
    try:
        with open(credentials_file, encoding="utf-8") as file:
            return json.load(file).get("client_email") or "почта сервисного аккаунта"
    except (OSError, ValueError, AttributeError):
        return "почта сервисного аккаунта"


@contextmanager
def _google_errors(credentials_file: str) -> Iterator[None]:
    """Превращает ошибки Google и сети в понятные администратору."""
    try:
        yield
    except GoogleSheetsError:
        raise
    except (gspread.exceptions.SpreadsheetNotFound, PermissionError) as error:
        email = _service_account_email(credentials_file)
        details = f"\n\nОтвет Google: {error.__cause__}" if error.__cause__ else ""
        raise GoogleSheetsError(
            "Таблица не найдена или нет доступа. Проверьте ссылку в "
            "GOOGLE_TABLE, затем откройте в таблице «Настройки доступа» и "
            f"добавьте {email} с правами «Редактор». Также проверьте, что "
            "в Google Cloud включён Google Sheets API." + details
        ) from error
    except gspread.exceptions.APIError as error:
        raise GoogleSheetsError(f"Google вернул ошибку: {error}") from error
    except TransportError as error:
        raise GoogleSheetsError(
            f"Не удалось связаться с Google: {error}"
        ) from error
    except GoogleAuthError as error:
        raise GoogleSheetsError(
            "Google не принял ключ сервисного аккаунта. Возможно, ключ удалён "
            f"в Google Cloud — создайте новый и замените {credentials_file}.\n\n"
            f"Подробности: {error}"
        ) from error
    except RequestException as error:
        raise GoogleSheetsError(
            f"Не удалось связаться с Google: {error}"
        ) from error


def open_spreadsheet(
        table: str | None,
        credentials_file: str = CREDENTIALS_FILE,
    ) -> gspread.Spreadsheet:
    """Открывает таблицу по ссылке или ID из GOOGLE_TABLE."""
    if not table:
        raise GoogleSheetsError(
            "Не задана таблица: добавьте в .env строку GOOGLE_TABLE со ссылкой "
            "на Google Таблицу и перезапустите сайт."
        )
    if not Path(credentials_file).is_file():
        raise GoogleSheetsError(
            f"Нет файла {credentials_file} с ключом сервисного аккаунта. "
            "Положите его рядом с main.py."
        )

    try:
        client = gspread.service_account(filename=credentials_file)
    except (ValueError, KeyError) as error:
        raise GoogleSheetsError(
            f"{credentials_file} не похож на ключ сервисного аккаунта "
            f"(нужен JSON с \"type\": \"service_account\"): {error}"
        ) from error

    with _google_errors(credentials_file):
        try:
            if table.startswith("http"):
                return client.open_by_url(table)
            return client.open_by_key(table)
        except gspread.exceptions.NoValidUrlKeyFound as error:
            raise GoogleSheetsError(
                "Не получилось найти ID таблицы в GOOGLE_TABLE. Скопируйте "
                "ссылку из адресной строки открытой таблицы."
            ) from error


def _cell(value: object) -> object:
    return "" if value is None else value


def _worksheet(
        spreadsheet: gspread.Spreadsheet,
        title: str,
        rows: int,
        cols: int,
    ) -> gspread.Worksheet:
    """Лист с нужным названием; если его нет — создаёт."""
    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def write_tables(
        spreadsheet: gspread.Spreadsheet,
        tables: dict[str, list[dict]],
    ) -> dict[str, int]:
    """Стирает листы и записывает в них таблицы. Возвращает число строк."""
    counts = {}
    for title, columns in SHEET_COLUMNS.items():
        values = [list(columns)] + [
            [_cell(row[column]) for column in columns]
            for row in tables[title]
        ]
        # Запасная строка: Google не даёт закрепить все строки листа.
        rows_needed = len(values) + 1
        worksheet = _worksheet(
            spreadsheet, title, max(rows_needed, 100), len(columns)
        )
        worksheet.clear()
        if worksheet.row_count < rows_needed or worksheet.col_count < len(columns):
            worksheet.resize(
                rows=max(worksheet.row_count, rows_needed),
                cols=max(worksheet.col_count, len(columns)),
            )
        # raw=True: значения записываются как есть, без превращения
        # строк в даты или формулы.
        worksheet.update(values, "A1", raw=True)
        header_range = f"A1:{gspread.utils.rowcol_to_a1(1, len(columns))}"
        worksheet.format(header_range, {"textFormat": {"bold": True}})
        worksheet.freeze(rows=1)
        counts[title] = len(values) - 1
    return counts


def read_tables(spreadsheet: gspread.Spreadsheet) -> dict[str, list[list[str]]]:
    """Читает все значения листов products, freezer и fridge."""
    sheets = {}
    missing = []
    for title in SHEET_COLUMNS:
        try:
            sheets[title] = spreadsheet.worksheet(title).get_all_values()
        except gspread.exceptions.WorksheetNotFound:
            missing.append(title)
    if missing:
        raise ImportDataError(
            [f"В таблице нет листа «{title}»." for title in missing]
        )
    return sheets


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _positive_int(value: str) -> int | None:
    """«12», «12.0», «1 000» -> число; пусто, ноль и мусор -> None."""
    text = value.replace(" ", "").replace(" ", "")
    match = re.fullmatch(r"(\d+)(?:[.,]0+)?", text)
    if match is None:
        return None
    number = int(match.group(1))
    return number if 0 < number <= MAX_NUMBER else None


def _date(value: str) -> str | None:
    """«2026-10-05» или «05.10.2026» -> «2026-10-05»."""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sheet_rows(
        title: str,
        values: list[list[str]],
        errors: list[str],
    ) -> list[tuple[int, dict[str, str]]]:
    """Непустые строки листа: (номер строки в таблице, {столбец: значение})."""
    if not values or not any(str(cell).strip() for cell in values[0]):
        errors.append(
            f"{title}: лист пуст — в первой строке должны быть названия столбцов."
        )
        return []

    header = [str(cell).strip().lower() for cell in values[0]]
    missing = [column for column in REQUIRED_COLUMNS[title] if column not in header]
    if missing:
        errors.append(f"{title}: нет столбцов {', '.join(missing)}.")
        return []

    rows = []
    for number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        record = {
            column: str(row[index]).strip() if index < len(row) else ""
            for index, column in enumerate(header)
            if column in SHEET_COLUMNS[title]
        }
        rows.append((number, record))
    return rows


def _parse_products(
        values: list[list[str]],
        errors: list[str],
    ) -> list[dict]:
    products = []
    seen: dict[str, int] = {}
    for number, record in _sheet_rows("products", values, errors):
        where = f"products, строка {number}"
        name = _clean_text(record.get("name", ""))
        fridge_days = _positive_int(record.get("fridge_storage_time", ""))
        freezer_text = record.get("freezer_storage_time", "")
        freezer_days = _positive_int(freezer_text) if freezer_text else None

        if not name:
            errors.append(f"{where}: не указано название (name).")
        elif name.casefold() in seen:
            errors.append(
                f"{where}: товар «{name}» уже есть в строке {seen[name.casefold()]}."
            )
        else:
            seen[name.casefold()] = number
        if fridge_days is None:
            errors.append(
                f"{where}: fridge_storage_time — срок хранения после "
                "разморозки в днях, целое число больше нуля."
            )
        if freezer_text and freezer_days is None:
            errors.append(
                f"{where}: freezer_storage_time — целое число больше нуля "
                "или пустая ячейка."
            )

        products.append({
            "name": name,
            "fridge_storage_time": fridge_days,
            "freezer_storage_time": freezer_days,
            "category": _clean_text(record.get("category", "")) or None,
        })
    return products


def _parse_freezer(
        values: list[list[str]],
        product_names: set[str],
        errors: list[str],
    ) -> list[dict]:
    freezer = []
    seen: dict[str, int] = {}
    for number, record in _sheet_rows("freezer", values, errors):
        where = f"freezer, строка {number}"
        name = _clean_text(record.get("product_name", ""))
        quantity = _positive_int(record.get("quantity", ""))

        if not name:
            errors.append(f"{where}: не указан товар (product_name).")
        elif name in seen:
            errors.append(f"{where}: товар «{name}» уже есть в строке {seen[name]}.")
        elif name not in product_names:
            errors.append(
                f"{where}: товара «{name}» нет на листе products — без него "
                "товар нельзя будет разморозить."
            )
        else:
            seen[name] = number
        if quantity is None:
            errors.append(f"{where}: quantity — целое число больше нуля.")

        freezer.append({"product_name": name, "quantity": quantity})
    return freezer


def _parse_fridge(
        values: list[list[str]],
        errors: list[str],
    ) -> list[dict]:
    fridge = []
    seen: dict[int, int] = {}
    today = datetime.now().strftime("%Y-%m-%d")
    for number, record in _sheet_rows("fridge", values, errors):
        where = f"fridge, строка {number}"
        id_text = record.get("id", "")
        batch_id = _positive_int(id_text) if id_text else None
        name = _clean_text(record.get("product_name", ""))
        quantity = _positive_int(record.get("quantity", ""))
        added_text = record.get("date_added", "")
        date_added = _date(added_text) if added_text else today
        expiration_date = _date(record.get("expiration_date", ""))

        if id_text and batch_id is None:
            errors.append(f"{where}: id — целое число больше нуля или пустая ячейка.")
        elif batch_id is not None and batch_id in seen:
            errors.append(f"{where}: партия с id {batch_id} уже есть в строке {seen[batch_id]}.")
        elif batch_id is not None:
            seen[batch_id] = number
        if not name:
            errors.append(f"{where}: не указан товар (product_name).")
        if quantity is None:
            errors.append(f"{where}: quantity — целое число больше нуля.")
        if date_added is None:
            errors.append(
                f"{where}: date_added — дата в формате ГГГГ-ММ-ДД или "
                "ДД.ММ.ГГГГ, либо пустая ячейка (тогда сегодня)."
            )
        if expiration_date is None:
            errors.append(
                f"{where}: expiration_date — дата в формате ГГГГ-ММ-ДД "
                "или ДД.ММ.ГГГГ."
            )
        elif date_added is not None and expiration_date < date_added:
            errors.append(f"{where}: срок годности раньше даты добавления.")

        fridge.append({
            "id": batch_id,
            "product_name": name,
            "quantity": quantity,
            "date_added": date_added,
            "expiration_date": expiration_date,
        })
    return fridge


def parse_tables(sheets: dict[str, list[list[str]]]) -> dict[str, list[dict]]:
    """Проверяет значения листов и превращает их в строки для базы.

    Если хоть одна строка с ошибкой, бросает ImportDataError со списком
    всех ошибок.
    """
    errors: list[str] = []
    products = _parse_products(sheets["products"], errors)
    product_names = {product["name"] for product in products}
    freezer = _parse_freezer(sheets["freezer"], product_names, errors)
    fridge = _parse_fridge(sheets["fridge"], errors)

    if errors:
        raise ImportDataError(errors)
    return {"products": products, "freezer": freezer, "fridge": fridge}


def export_to_google(
        db: Database,
        table: str | None,
        credentials_file: str = CREDENTIALS_FILE,
    ) -> dict[str, int]:
    """Перезаписывает листы products, freezer и fridge данными из базы."""
    spreadsheet = open_spreadsheet(table, credentials_file)
    with _google_errors(credentials_file):
        return write_tables(spreadsheet, db.stock_tables())


def import_from_google(
        db: Database,
        table: str | None,
        credentials_file: str = CREDENTIALS_FILE,
    ) -> tuple[dict[str, int], str]:
    """Заменяет товары, морозильник и холодильник в базе данными из таблицы.

    Сначала проверяются все строки: при ошибке база не меняется. Перед
    заменой сохраняется копия базы. Возвращает число строк по листам
    и путь к копии.
    """
    spreadsheet = open_spreadsheet(table, credentials_file)
    with _google_errors(credentials_file):
        sheets = read_tables(spreadsheet)
    tables = parse_tables(sheets)

    backup_path = str(
        Path(db.path_to_db).parent / "backups"
        / f"before_import_{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
    )
    db.backup(backup_path)
    db.replace_stock_tables(**tables)
    return {title: len(rows) for title, rows in tables.items()}, backup_path
