"""Редактор всех таблиц базы для администратора.

Правки идут мимо проверок сайта (например, переименование товара здесь
не переносит остатки), поэтому каждая правка пишется в журнал действий,
а сам журнал здесь только читается.
"""
import csv
import io

from flask import (
    Blueprint, Response, abort, flash, redirect, render_template, request,
    url_for,
)

from storage.db import READ_ONLY_TABLES
from web.auth import require_admin
from web.utils import audit, get_db, make_page, page_arg


bp = Blueprint("database", __name__, url_prefix="/admin/db")
bp.before_request(require_admin)

ROWS_PER_PAGE = 50
# Хеш пароля не показывается и не редактируется: пароль задают в «Сотрудниках».
HIDDEN_COLUMNS = {"users": ("password_hash",)}
TABLE_TITLES = {
    "products": "Справочник товаров",
    "freezer": "Морозильник",
    "fridge": "Партии в холодильнике",
    "operations": "Журнал операций",
    "users": "Пользователи сайта",
    "errors": "Ошибки",
    "daily_notifications": "Уведомления за день",
    "audit_log": "Журнал действий (только чтение)",
}
TABLE_NOTES = {
    "products": (
        "Переименовывать товары лучше в разделе «Товары»: там название "
        "меняется и у остатков в морозильнике и холодильнике."
    ),
    "users": (
        "Пароль здесь не виден и не меняется — его задают в разделе "
        "«Сотрудники». Пользователь без пароля войти не может."
    ),
    "operations": (
        "Это история работы сотрудников. Правка записи не меняет остатки."
    ),
}
MAX_AUDIT_VALUE = 80


def _table(table: str) -> list[dict]:
    """Столбцы таблицы без скрытых; неизвестная таблица — 404."""
    try:
        columns = get_db().table_columns(table)
    except KeyError:
        abort(404)
    hidden = HIDDEN_COLUMNS.get(table, ())
    for column in columns:
        column["hidden"] = column["name"] in hidden
        column["kind"] = _kind(column["type"])
    return columns


def _kind(column_type: str) -> str:
    """Как показывать поле: integer, real, boolean или text."""
    if "BOOL" in column_type:
        return "boolean"
    if "INT" in column_type:
        return "integer"
    if any(word in column_type for word in ("REAL", "FLOA", "DOUB", "NUM")):
        return "real"
    return "text"


def _read_form(columns: list[dict]) -> tuple[dict, dict[str, str]]:
    """Значения из формы с приведением типов: (значения, ошибки по столбцам).

    Пустое поле — NULL, если столбец его допускает. Отметка «NULL»
    явно записывает пустое значение.
    """
    values, errors = {}, {}
    for column in columns:
        if column["hidden"]:
            continue
        name = column["name"]
        raw = request.form.get(f"col_{name}", "")
        if request.form.get(f"null_{name}") or (raw == "" and not column["notnull"]):
            values[name] = None
            continue

        kind = column["kind"]
        if kind in ("integer", "boolean"):
            try:
                values[name] = int(raw.strip())
            except ValueError:
                errors[name] = "Нужно целое число."
        elif kind == "real":
            try:
                values[name] = float(raw.strip().replace(",", "."))
            except ValueError:
                errors[name] = "Нужно число."
        else:
            values[name] = raw
    return values, errors


def _short(value: object) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= MAX_AUDIT_VALUE else text[:MAX_AUDIT_VALUE] + "…"


@bp.get("/")
def tables():
    db = get_db()
    items = [
        {
            "name": name,
            "title": TABLE_TITLES.get(name, ""),
            "count": db.table_count(name),
            "read_only": name in READ_ONLY_TABLES,
        }
        for name in db.table_names()
    ]
    return render_template("admin/db_tables.html", tables=items)


@bp.get("/<table>")
def table_view(table: str):
    columns = _table(table)
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort")
    descending = request.args.get("desc") == "1"
    page = page_arg()
    total, rows = get_db().table_rows(
        table, page=page, limit=ROWS_PER_PAGE, query=query or None,
        sort=sort, descending=descending,
    )
    return render_template(
        "admin/db_table.html",
        table=table,
        title=TABLE_TITLES.get(table, ""),
        note=TABLE_NOTES.get(table),
        columns=columns,
        page=make_page(total, rows, page, ROWS_PER_PAGE),
        query=query,
        sort=sort,
        descending=descending,
        read_only=table in READ_ONLY_TABLES,
    )


@bp.get("/<table>/export.csv")
def table_export(table: str):
    columns = [column for column in _table(table) if not column["hidden"]]
    db = get_db()
    total = db.table_count(table)
    _, rows = db.table_rows(table, limit=max(total, 1))

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([column["name"] for column in columns])
    for row in rows:
        writer.writerow(["" if row[c["name"]] is None else row[c["name"]] for c in columns])
    # BOM — чтобы Excel сразу открыл кириллицу в UTF-8.
    return Response(
        "﻿" + output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table}.csv"},
    )


@bp.route("/<table>/new", methods=["GET", "POST"])
def row_new(table: str):
    columns = _table(table)
    if table in READ_ONLY_TABLES:
        abort(403)

    values, errors, error = {}, {}, None
    if request.method == "POST":
        values, errors = _read_form(columns)
        if not errors:
            # Пустой id (NULL) SQLite заменит следующим номером.
            try:
                rowid = get_db().insert_row(table, values)
            except ValueError as db_error:
                error = str(db_error)
            else:
                audit(
                    "db_insert",
                    f"{table} #{rowid}: " + "; ".join(
                        f"{name}={_short(value)}" for name, value in values.items()
                    ),
                )
                flash(f"Строка добавлена в {table}.", "success")
                return redirect(url_for("database.table_view", table=table))

    return render_template(
        "admin/db_row.html", table=table, columns=columns, row=None,
        values=values or {}, errors=errors, error=error,
        form=request.form if request.method == "POST" else None,
        note=TABLE_NOTES.get(table),
    ), 400 if error or errors else 200


@bp.route("/<table>/<int:rowid>", methods=["GET", "POST"])
def row_edit(table: str, rowid: int):
    columns = _table(table)
    db = get_db()
    row = db.table_row(table, rowid)
    if row is None:
        flash("Строка не найдена: возможно, её уже удалили.", "error")
        return redirect(url_for("database.table_view", table=table))

    read_only = table in READ_ONLY_TABLES
    errors, error = {}, None
    if request.method == "POST":
        if read_only:
            abort(403)
        values, errors = _read_form(columns)
        if not errors:
            changed = {
                name: value for name, value in values.items()
                if row[name] != value
            }
            try:
                db.update_row(table, rowid, changed)
            except ValueError as db_error:
                error = str(db_error)
            else:
                if changed:
                    audit(
                        "db_update",
                        f"{table} #{rowid}: " + "; ".join(
                            f"{name}: {_short(row[name])} → {_short(value)}"
                            for name, value in changed.items()
                        ),
                    )
                    flash("Изменения сохранены.", "success")
                else:
                    flash("Ничего не изменилось.", "info")
                return redirect(url_for("database.table_view", table=table))

    return render_template(
        "admin/db_row.html", table=table, columns=columns, row=row,
        values=row, errors=errors, error=error, read_only=read_only,
        form=request.form if request.method == "POST" else None,
        note=TABLE_NOTES.get(table),
    ), 400 if error or errors else 200


@bp.post("/<table>/<int:rowid>/delete")
def row_delete(table: str, rowid: int):
    _table(table)
    if table in READ_ONLY_TABLES:
        abort(403)
    db = get_db()
    row = db.table_row(table, rowid)
    try:
        db.delete_row(table, rowid)
    except ValueError as error:
        flash(str(error), "error")
    else:
        hidden = HIDDEN_COLUMNS.get(table, ())
        audit(
            "db_delete",
            f"{table} #{rowid}: " + "; ".join(
                f"{name}={_short(value)}" for name, value in row.items()
                if name != "__rowid" and name not in hidden
            ),
        )
        flash(f"Строка #{rowid} удалена из {table}.", "success")
    return redirect(url_for("database.table_view", table=table))
