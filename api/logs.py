"""Логи для администратора: операции, изменения, ошибки, журнал сервера."""
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import admin_user, get_db, get_settings
from api.staff import paged
from storage import queries
from storage.db import Database
from storage.table_editor import OPERATION_TITLES


router = APIRouter(prefix="/admin/logs", tags=["logs"], dependencies=[Depends(admin_user)])

LOG_PAGE_SIZE = 50
SERVER_LOG_LINES = (100, 300, 1000)


def _date(text: str | None) -> str | None:
    try:
        return datetime.strptime(text or "", "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


@router.get("/operations")
def operations(page: int = 1, type: str | None = None, user: int | None = None,
               q: str = "", date_from: str | None = None, date_to: str | None = None,
               db: Database = Depends(get_db)):
    page = max(page, 1)
    total, items = queries.operations_log(
        db, page=page, limit=LOG_PAGE_SIZE,
        operation_type=type if type in OPERATION_TITLES else None,
        user_id=user, query=q.strip() or None,
        date_from=_date(date_from), date_to=_date(date_to),
    )
    return paged(total, items, page, LOG_PAGE_SIZE)


@router.get("/changes")
def changes(page: int = 1, q: str = "", db: Database = Depends(get_db)):
    page = max(page, 1)
    total, items = queries.change_log(db, page=page, limit=LOG_PAGE_SIZE, query=q.strip() or None)
    return paged(total, items, page, LOG_PAGE_SIZE)


@router.get("/errors")
def errors(page: int = 1, db: Database = Depends(get_db)):
    page = max(page, 1)
    total, items = queries.errors_list(db, page=page, limit=LOG_PAGE_SIZE)
    return paged(total, items, page, LOG_PAGE_SIZE)


@router.get("/server")
def server(lines: int = SERVER_LOG_LINES[0], settings: dict = Depends(get_settings)):
    if lines not in SERVER_LOG_LINES:
        lines = SERVER_LOG_LINES[0]
    log_file = Path(settings["log_file"])
    result = []
    if log_file.is_file():
        with log_file.open(encoding="utf-8", errors="replace") as file:
            result = [line.rstrip("\n") for line in deque(file, maxlen=lines)]
    result.reverse()  # новые сверху
    return {"file": str(log_file), "exists": log_file.is_file(), "lines": result,
            "options": SERVER_LOG_LINES}
