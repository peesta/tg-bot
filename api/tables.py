"""Редактор таблиц базы для администратора (таблица как в Excel)."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import admin_user, get_db
from api.staff import paged
from storage import table_editor
from storage.db import Database


router = APIRouter(prefix="/admin/tables", tags=["tables"], dependencies=[Depends(admin_user)])

ROWS_PER_PAGE = 50


class RowValues(BaseModel):
    values: dict


def _table(name: str) -> table_editor.Table:
    try:
        return table_editor.table_spec(name)
    except KeyError:
        raise HTTPException(404, "Такой таблицы нет") from None


@router.get("")
def tables(db: Database = Depends(get_db)):
    return table_editor.list_tables(db)


@router.get("/{name}")
def table_rows(name: str, page: int = 1, q: str = "", sort: str | None = None,
               desc: bool | None = None, db: Database = Depends(get_db)):
    table = _table(name)
    page = max(page, 1)
    total, rows = table_editor.rows(
        db, table, page=page, limit=ROWS_PER_PAGE, query=q.strip() or None,
        sort=sort, descending=desc,
    )
    options = table_editor.options(db, table)
    return {
        "name": table.name,
        "title": table.title,
        "description": table.description,
        "note": table.note,
        "can_insert": table.can_insert,
        "columns": [
            {**asdict(column), "options": options.get(column.name)}
            for column in table.columns
        ],
        **paged(total, rows, page, ROWS_PER_PAGE),
    }


@router.post("/{name}/rows")
def row_add(name: str, form: RowValues, user: dict = Depends(admin_user),
            db: Database = Depends(get_db)):
    table = _table(name)
    rowid = table_editor.insert_row(db, table, form.values, user)
    return table_editor.get_row(db, table, rowid)


@router.patch("/{name}/rows/{rowid}")
def row_update(name: str, rowid: int, form: RowValues, user: dict = Depends(admin_user),
               db: Database = Depends(get_db)):
    return table_editor.update_row(db, _table(name), rowid, form.values, user)


@router.delete("/{name}/rows/{rowid}")
def row_delete(name: str, rowid: int, user: dict = Depends(admin_user),
               db: Database = Depends(get_db)):
    table_editor.delete_row(db, _table(name), rowid, user)
    return {"ok": True}
