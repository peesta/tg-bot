"""Разделы для всех сотрудников — то, что в боте было главным меню.

Даты отдаются как в базе (ГГГГ-ММ-ДД), формат ДД.ММ.ГГГГ — на клиенте.
"""
from datetime import datetime, timedelta
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import current_user, get_db
from storage import queries
from storage.db import Database
from storage.table_editor import OPERATION_TITLES


router = APIRouter(tags=["staff"])

WRITE_OFF_REASONS = {
    "expired": "Просрочено",
    "damaged": "Повреждено",
    "staff": "Для сотрудника",
}
MAX_QUANTITY = 100_000
MAX_REASON_LENGTH = 200
HISTORY_PAGE_SIZE = 20
RECENT_ROWS = 10


class StockForm(BaseModel):
    product_id: int
    quantity: int


class DeliveryForm(StockForm):
    # Куда поставка: в морозильник (как раньше) или сразу в холодильник.
    destination: Literal["freezer", "fridge"] = "freezer"


class WriteOffForm(BaseModel):
    reason: str
    reason_text: str | None = None
    quantity: int | None = None
    whole: bool = False


class SaleForm(BaseModel):
    quantity: int | None = None
    whole: bool = False


def paged(total: int, items: list, page: int, limit: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(ceil(total / limit), 1),
    }


def batch_status(expiration_date: str) -> str:
    """expired — просрочено, today — срок истекает сегодня, fresh — годно."""
    current_date = queries.today()
    if expiration_date < current_date:
        return "expired"
    if expiration_date == current_date:
        return "today"
    return "fresh"


def batches(db: Database) -> list[dict]:
    return [
        {**batch, "status": batch_status(batch["expiration_date"])}
        for batch in db.fridge_batches_list()
    ]


def sum_by_product(items: list[dict]) -> list[dict]:
    """[{product_name, quantity}] по партиям, в порядке первого появления."""
    totals: dict[str, int] = {}
    for item in items:
        totals[item["product_name"]] = totals.get(item["product_name"], 0) + item["quantity"]
    return [{"product_name": name, "quantity": quantity} for name, quantity in totals.items()]


def expires_after(days: int | None) -> str | None:
    """Дата «годен до» для партии, которая появится в холодильнике сегодня."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d") if days else None


def check_quantity(quantity: int | None, maximum: int, where: str) -> int:
    if quantity is None or not 1 <= quantity <= maximum:
        raise ValueError(f"Количество — целое число от 1 до {maximum} ({where})")
    return quantity


def expiring_groups(db: Database) -> dict:
    items = batches(db)
    today_items = [batch for batch in items if batch["status"] == "today"]
    expired = [batch for batch in items if batch["status"] == "expired"]
    return {
        "today": today_items,
        "expired": expired,
        "today_totals": sum_by_product(today_items),
        "expired_totals": sum_by_product(expired),
    }


@router.get("/dashboard")
def dashboard(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    groups = expiring_groups(db)
    result = {
        "expiring_today": len(groups["today"]),
        "expired": len(groups["expired"]),
    }
    if user["role"] == "admin":
        result["stats"] = queries.stats(db)
        result["operations"] = queries.operations_log(db, limit=RECENT_ROWS)[1]
        result["changes"] = queries.change_log(db, limit=6)[1]
    else:
        result["my_operations"] = queries.operations_log(
            db, limit=RECENT_ROWS, user_id=user["id"], date_from=queries.today()
        )[1]
    return result


@router.get("/notice")
def notice(
    skip: bool = False,
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
):
    """Уведомление в начале смены: после первого за день открытия сайта.

    skip — сайт открыт сразу на «Скоро испортится», там тот же список.
    """
    first_today = db.mark_daily_notification(user["id"], queries.today())
    groups = expiring_groups(db)
    show = first_today and not skip and bool(groups["today"] or groups["expired"])
    return {
        "show": show,
        "today": groups["today_totals"] if show else [],
        "expired": groups["expired_totals"] if show else [],
    }


@router.get("/expiring")
def expiring(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    return expiring_groups(db)


@router.post("/expiring/clear")
def expiring_clear(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    result = db.clear_expired_product(user_id=user["id"])
    if result is False:
        return {"message": "Просроченных партий и партий с истекающим сегодня сроком нет"}
    return {"message": result}


@router.get("/freezer")
def freezer(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    items = queries.freezer_items(db)
    for item in items:
        item["expires"] = expires_after(item["fridge_storage_time"])
    return items


@router.post("/defrost")
def defrost(form: StockForm, user: dict = Depends(current_user), db: Database = Depends(get_db)):
    product = db.get_freezer_product_by_id(form.product_id)
    if product is None:
        raise ValueError("Этого продукта уже нет в морозильнике")
    quantity = check_quantity(form.quantity, product["quantity"], "столько в морозильнике")
    batch = db.move_to_fridge(product["product_name"], quantity, user_id=user["id"])
    # quantity — сколько разморозили, batch_quantity — сколько теперь в партии
    # (сегодняшние разморозки одного товара хранятся одной партией).
    return {
        **batch,
        "quantity": quantity,
        "batch_quantity": batch["quantity"],
        "defrosted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/catalog")
def catalog(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    items = queries.catalog(db)
    for item in items:
        item["expires"] = expires_after(item["fridge_storage_time"])
    return items


@router.post("/delivery")
def delivery(form: DeliveryForm, user: dict = Depends(current_user), db: Database = Depends(get_db)):
    product = db.get_product_by_id(form.product_id)
    if product is None:
        raise ValueError("Этого товара уже нет в справочнике")
    quantity = check_quantity(form.quantity, MAX_QUANTITY, "одна поставка")
    if form.destination == "fridge":
        batch = db.new_fridge_delivery(product["name"], quantity, user_id=user["id"])
        return {
            "destination": "fridge",
            "product_name": product["name"],
            "quantity": quantity,
            "batch_id": batch["id"],
            "batch_quantity": batch["quantity"],
            "expiration_date": batch["expiration_date"],
        }
    db.new_delivery(product["name"], quantity, user_id=user["id"])
    return {
        "destination": "freezer",
        "product_name": product["name"],
        "quantity": quantity,
        "in_freezer": db.get_freezer_product(product["name"])["quantity"],
    }


@router.get("/batches")
def batch_list(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    return batches(db)


def _batch(db: Database, batch_id: int) -> dict:
    batch = db.get_fridge_batch(batch_id)
    if batch is None:
        raise HTTPException(404, "Этой партии уже нет: её списали или продали полностью")
    return {**batch, "status": batch_status(batch["expiration_date"])}


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int, user: dict = Depends(current_user), db: Database = Depends(get_db)):
    return {**_batch(db, batch_id), "reasons": WRITE_OFF_REASONS}


def _close(db: Database, batch: dict, quantity: int, operation_type: str,
           user: dict, reason: str | None = None) -> dict:
    result = db.clear_expired_product(
        id=batch["id"], quantity=quantity, operation_type=operation_type,
        user_id=user["id"], reason=reason,
    )
    if result is False:
        raise ValueError("Не получилось: партия уже закрыта или в ней меньше товара")
    return {"message": result}


@router.post("/batches/{batch_id}/write-off")
def write_off(batch_id: int, form: WriteOffForm,
              user: dict = Depends(current_user), db: Database = Depends(get_db)):
    batch = _batch(db, batch_id)
    if form.reason == "other":
        reason = " ".join((form.reason_text or "").split())
        if not reason:
            raise ValueError("Напишите причину списания")
        if len(reason) > MAX_REASON_LENGTH:
            raise ValueError(f"Причина — не длиннее {MAX_REASON_LENGTH} символов")
    elif form.reason in WRITE_OFF_REASONS:
        reason = WRITE_OFF_REASONS[form.reason]
    else:
        raise ValueError("Выберите причину списания")
    quantity = batch["quantity"] if form.whole else check_quantity(
        form.quantity, batch["quantity"], "столько в партии"
    )
    return _close(db, batch, quantity, "write_off", user, reason)


@router.post("/batches/{batch_id}/sale")
def sale(batch_id: int, form: SaleForm,
         user: dict = Depends(current_user), db: Database = Depends(get_db)):
    batch = _batch(db, batch_id)
    quantity = batch["quantity"] if form.whole else check_quantity(
        form.quantity, batch["quantity"], "столько в партии"
    )
    return _close(db, batch, quantity, "sale", user)


@router.get("/stock")
def stock(user: dict = Depends(current_user), db: Database = Depends(get_db)):
    groups = {"fresh": [], "today": [], "expired": []}
    for batch in batches(db):
        groups[batch["status"]].append(batch)
    return {**groups, "freezer": queries.freezer_items(db)}


@router.get("/history")
def history(page: int = 1, type: str | None = None,
            user: dict = Depends(current_user), db: Database = Depends(get_db)):
    """История операций; type — sale, write_off и т.д., без него — все."""
    page = max(page, 1)
    total, items = queries.operations_log(
        db, page=page, limit=HISTORY_PAGE_SIZE,
        operation_type=type if type in OPERATION_TITLES else None,
    )
    return paged(total, items, page, HISTORY_PAGE_SIZE)
