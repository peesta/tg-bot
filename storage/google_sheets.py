"""Экспорт и импорт товаров, морозильника и холодильника в Google Таблицу.

В таблице три листа на русском: «Товары», «Морозильник», «Холодильник».
В первой строке листа — названия столбцов на русском, даты — ДД.ММ.ГГГГ.
База при этом не меняется: в ней таблицы products, freezer, fridge.
Листы и столбцы со старыми английскими названиями (как в базе) импорт
тоже понимает, а экспорт переименовывает такие листы по-русски.

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

# Таблица базы → название листа в Google Таблице.
SHEET_TITLES = {
    "products": "Товары",
    "freezer": "Морозильник",
    "fridge": "Холодильник",
}
# Столбцы каждого листа в порядке выгрузки: столбец базы → заголовок
# (как в разделе «База данных»).
SHEET_COLUMNS = {
    "products": {
        "name": "Название",
        "fridge_storage_time": "Срок после разморозки, дней",
        "freezer_storage_time": "Срок в морозильнике, дней",
        "category": "Категория",
    },
    "freezer": {
        "product_name": "Товар",
        "quantity": "Количество, шт.",
    },
    "fridge": {
        "id": "№ партии",
        "product_name": "Товар",
        "quantity": "Количество, шт.",
        "date_added": "Добавлено",
        "expiration_date": "Годен до",
    },
}
# В таблице даты — ДД.ММ.ГГГГ, в базе — ГГГГ-ММ-ДД.
DATE_COLUMNS = ("date_added", "expiration_date")
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


def _cell(column: str, value: object) -> object:
    """Значение из базы для ячейки: пусто вместо None, даты — ДД.ММ.ГГГГ."""
    if value is None:
        return ""
    if column in DATE_COLUMNS:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(value))
        if match:
            return f"{match[3]}.{match[2]}.{match[1]}"
    return value


def _find_worksheet(
        spreadsheet: gspread.Spreadsheet,
        table: str,
    ) -> gspread.Worksheet | None:
    """Лист таблицы базы: по-русски («Товары») или по-старому («products»)."""
    for title in (SHEET_TITLES[table], table):
        try:
            return spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            continue
    return None


def _worksheet(
        spreadsheet: gspread.Spreadsheet,
        table: str,
        rows: int,
        cols: int,
    ) -> gspread.Worksheet:
    """Лист для выгрузки. Старый лист («products») переименовывает
    по-русски, чтобы в таблице не было двух листов с одним и тем же;
    если листа нет — создаёт."""
    title = SHEET_TITLES[table]
    worksheet = _find_worksheet(spreadsheet, table)
    if worksheet is None:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
    if worksheet.title != title:
        worksheet.update_title(title)
    return worksheet


def write_tables(
        spreadsheet: gspread.Spreadsheet,
        tables: dict[str, list[dict]],
    ) -> dict[str, int]:
    """Стирает листы и записывает в них таблицы. Возвращает число строк
    по таблицам базы: {"products": …, "freezer": …, "fridge": …}."""
    counts = {}
    for table, headers in SHEET_COLUMNS.items():
        columns = list(headers)
        values = [list(headers.values())] + [
            [_cell(column, row[column]) for column in columns]
            for row in tables[table]
        ]
        # Запасная строка: Google не даёт закрепить все строки листа.
        rows_needed = len(values) + 1
        worksheet = _worksheet(
            spreadsheet, table, max(rows_needed, 100), len(columns)
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
        counts[table] = len(values) - 1
    return counts


def read_tables(spreadsheet: gspread.Spreadsheet) -> dict[str, list[list[str]]]:
    """Читает все значения листов «Товары», «Морозильник» и «Холодильник»
    (или старых products, freezer и fridge) по таблицам базы."""
    sheets = {}
    missing = []
    for table, title in SHEET_TITLES.items():
        worksheet = _find_worksheet(spreadsheet, table)
        if worksheet is None:
            missing.append(title)
        else:
            sheets[table] = worksheet.get_all_values()
    if missing:
        raise ImportDataError(
            [f"В таблице нет листа «{title}»." for title in missing]
        )
    return sheets


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _header_key(text: object) -> str:
    """Заголовок для сравнения: без регистра, лишних пробелов и разницы е/ё."""
    return _clean_text(str(text)).casefold().replace("ё", "е")


def _column_aliases(table: str) -> dict[str, str]:
    """Заголовки, которые понимает импорт: «Количество, шт.», «Количество»
    и старое название столбца из базы («quantity»)."""
    aliases = {}
    for column, header in SHEET_COLUMNS[table].items():
        for text in (header, header.split(",")[0], column):
            aliases[_header_key(text)] = column
    return aliases


def _label(table: str, column: str) -> str:
    """«Количество, шт.» — как столбец называется в таблице."""
    return f"«{SHEET_COLUMNS[table][column]}»"


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
        table: str,
        values: list[list[str]],
        errors: list[str],
    ) -> list[tuple[int, dict[str, str]]]:
    """Непустые строки листа: (номер строки в таблице, {столбец базы: значение})."""
    title = SHEET_TITLES[table]
    if not values or not any(str(cell).strip() for cell in values[0]):
        errors.append(
            f"{title}: лист пуст — в первой строке должны быть названия столбцов."
        )
        return []

    aliases = _column_aliases(table)
    # Столбец базы для каждого столбца листа; None — чужой столбец (пропускается).
    header = [aliases.get(_header_key(cell)) for cell in values[0]]
    missing = [column for column in REQUIRED_COLUMNS[table] if column not in header]
    if missing:
        names = ", ".join(_label(table, column) for column in missing)
        errors.append(f"{title}: нет столбцов {names}.")
        return []

    rows = []
    for number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        record = {
            column: str(row[index]).strip() if index < len(row) else ""
            for index, column in enumerate(header)
            if column
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
        where = f"{SHEET_TITLES['products']}, строка {number}"
        name = _clean_text(record.get("name", ""))
        fridge_days = _positive_int(record.get("fridge_storage_time", ""))
        freezer_text = record.get("freezer_storage_time", "")
        freezer_days = _positive_int(freezer_text) if freezer_text else None

        if not name:
            errors.append(f"{where}: не указано название ({_label('products', 'name')}).")
        elif name.casefold() in seen:
            errors.append(
                f"{where}: товар «{name}» уже есть в строке {seen[name.casefold()]}."
            )
        else:
            seen[name.casefold()] = number
        if fridge_days is None:
            errors.append(
                f"{where}: {_label('products', 'fridge_storage_time')} — срок "
                "хранения после разморозки в днях, целое число больше нуля."
            )
        if freezer_text and freezer_days is None:
            errors.append(
                f"{where}: {_label('products', 'freezer_storage_time')} — целое "
                "число больше нуля или пустая ячейка."
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
        where = f"{SHEET_TITLES['freezer']}, строка {number}"
        name = _clean_text(record.get("product_name", ""))
        quantity = _positive_int(record.get("quantity", ""))

        if not name:
            errors.append(f"{where}: не указан товар ({_label('freezer', 'product_name')}).")
        elif name in seen:
            errors.append(f"{where}: товар «{name}» уже есть в строке {seen[name]}.")
        elif name not in product_names:
            errors.append(
                f"{where}: товара «{name}» нет на листе «{SHEET_TITLES['products']}» "
                "— без него товар нельзя будет разморозить."
            )
        else:
            seen[name] = number
        if quantity is None:
            errors.append(f"{where}: {_label('freezer', 'quantity')} — целое число больше нуля.")

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
        where = f"{SHEET_TITLES['fridge']}, строка {number}"
        id_text = record.get("id", "")
        batch_id = _positive_int(id_text) if id_text else None
        name = _clean_text(record.get("product_name", ""))
        quantity = _positive_int(record.get("quantity", ""))
        added_text = record.get("date_added", "")
        date_added = _date(added_text) if added_text else today
        expiration_date = _date(record.get("expiration_date", ""))

        if id_text and batch_id is None:
            errors.append(
                f"{where}: {_label('fridge', 'id')} — целое число больше нуля "
                "или пустая ячейка."
            )
        elif batch_id is not None and batch_id in seen:
            errors.append(f"{where}: партия с id {batch_id} уже есть в строке {seen[batch_id]}.")
        elif batch_id is not None:
            seen[batch_id] = number
        if not name:
            errors.append(f"{where}: не указан товар ({_label('fridge', 'product_name')}).")
        if quantity is None:
            errors.append(f"{where}: {_label('fridge', 'quantity')} — целое число больше нуля.")
        if date_added is None:
            errors.append(
                f"{where}: {_label('fridge', 'date_added')} — дата в формате "
                "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД, либо пустая ячейка (тогда сегодня)."
            )
        if expiration_date is None:
            errors.append(
                f"{where}: {_label('fridge', 'expiration_date')} — дата в формате "
                "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД."
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
    """Перезаписывает листы «Товары», «Морозильник» и «Холодильник»
    данными из базы."""
    spreadsheet = open_spreadsheet(table, credentials_file)
    with _google_errors(credentials_file):
        return write_tables(spreadsheet, db.stock_tables())


def import_from_google(
        db: Database,
        table: str | None,
        credentials_file: str = CREDENTIALS_FILE,
        user_id: int | None = None,
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
    db.replace_stock_tables(**tables, user_id=user_id)
    return {title: len(rows) for title, rows in tables.items()}, backup_path
