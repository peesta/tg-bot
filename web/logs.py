"""Логи для администратора: операции, действия на сайте, ошибки, сервер."""
import csv
import io
from collections import deque
from pathlib import Path

from flask import (
    Blueprint, Response, current_app, redirect, render_template, request,
    url_for,
)

from storage.db import OPERATION_TYPES
from web.auth import require_admin
from web.utils import (
    ACTION_TITLES, OPERATION_TITLES, format_datetime, get_db, make_page,
    page_arg, parse_date, parse_positive_int,
)


bp = Blueprint("logs", __name__, url_prefix="/admin/logs")
bp.before_request(require_admin)

LOG_PAGE_SIZE = 50
SERVER_LOG_LINES = (100, 300, 1000)
MAX_EXPORT_ROWS = 100_000


def _operation_filters() -> dict:
    operation_type = request.args.get("type")
    return {
        "operation_type": operation_type if operation_type in OPERATION_TYPES else None,
        "user_id": parse_positive_int(request.args.get("user")),
        "query": request.args.get("q", "").strip() or None,
        "date_from": parse_date(request.args.get("date_from")),
        "date_to": parse_date(request.args.get("date_to")),
    }


@bp.get("/")
def index():
    return redirect(url_for("logs.operations"))


@bp.get("/operations")
def operations():
    filters = _operation_filters()
    page = page_arg()
    total, rows = get_db().operations_log(page=page, limit=LOG_PAGE_SIZE, **filters)
    return render_template(
        "admin/logs_operations.html",
        tab="operations",
        filters=filters,
        users=get_db().users_list(),
        operation_types=OPERATION_TITLES,
        page=make_page(total, rows, page, LOG_PAGE_SIZE),
    )


@bp.get("/operations.csv")
def operations_export():
    _, rows = get_db().operations_log(limit=MAX_EXPORT_ROWS, **_operation_filters())
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Дата", "Операция", "Товар", "Количество", "Причина", "Партия",
        "Сотрудник",
    ])
    for row in rows:
        writer.writerow([
            format_datetime(row["created_at"]),
            OPERATION_TITLES.get(row["operation_type"], row["operation_type"]),
            row["product_name"],
            row["quantity"],
            row["reason"] or "",
            row["batch_id"] or "",
            row["full_name"] or f"ID {row['created_by']}",
        ])
    return Response(
        "﻿" + output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=operations.csv"},
    )


@bp.get("/audit")
def audit_log():
    action = request.args.get("action")
    action = action if action in ACTION_TITLES else None
    query = request.args.get("q", "").strip()
    page = page_arg()
    total, rows = get_db().audit_list(
        page=page, limit=LOG_PAGE_SIZE, action=action, query=query or None
    )
    return render_template(
        "admin/logs_audit.html",
        tab="audit",
        action=action,
        action_titles=ACTION_TITLES,
        query=query,
        page=make_page(total, rows, page, LOG_PAGE_SIZE),
    )


@bp.get("/errors")
def errors():
    page = page_arg()
    total, rows = get_db().errors_list(page=page, limit=LOG_PAGE_SIZE)
    return render_template(
        "admin/logs_errors.html",
        tab="errors",
        page=make_page(total, rows, page, LOG_PAGE_SIZE),
    )


@bp.get("/server")
def server():
    lines_count = parse_positive_int(request.args.get("lines"))
    if lines_count not in SERVER_LOG_LINES:
        lines_count = SERVER_LOG_LINES[0]

    log_file = Path(current_app.config["LOG_FILE"])
    lines = []
    if log_file.is_file():
        with log_file.open(encoding="utf-8", errors="replace") as file:
            lines = list(deque(file, maxlen=lines_count))
    lines.reverse()  # новые сверху
    return render_template(
        "admin/logs_server.html",
        tab="server",
        log_file=log_file,
        exists=log_file.is_file(),
        lines=lines,
        lines_count=lines_count,
        line_options=SERVER_LOG_LINES,
    )
