"""Разделы для всех сотрудников: то, что в боте было главным меню."""
from datetime import datetime, timedelta

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for,
)

from web.auth import require_login
from web.utils import (
    MAX_QUANTITY, MAX_REASON_LENGTH, PAGE_SIZE, WRITE_OFF_REASONS,
    batch_status, clean_name, format_date, get_db, make_page, matches,
    page_arg, paginate, parse_positive_int, sum_by_product, today,
)


bp = Blueprint("main", __name__)
bp.before_request(require_login)

RECENT_OPERATIONS = 10


def _search(items: list[dict], key: str) -> tuple[str, list[dict]]:
    query = request.args.get("q", "").strip()
    if query:
        items = [item for item in items if matches(item[key], query)]
    return query, items


def _back(endpoint: str, **values):
    """Возвращает на страницу списка с тем же поиском и номером страницы."""
    for name in ("q", "page"):
        if request.form.get(name):
            values[name] = request.form[name]
    return redirect(url_for(endpoint, **values))


def _form_quantity(maximum: int | None = None) -> int | None:
    """Количество из быстрой кнопки 1/2/3 или из поля ввода."""
    return parse_positive_int(
        request.form.get("quick") or request.form.get("quantity"), maximum
    )


def _expiring() -> tuple[list[dict], list[dict]]:
    """(просроченные, истекающие сегодня) партии."""
    return get_db().get_expiring_products() or ([], [])


@bp.get("/")
def dashboard():
    db = get_db()
    expired, expiring_today = _expiring()
    if g.user["role"] == "admin":
        _, operations = db.operations_log(limit=RECENT_OPERATIONS)
        _, actions = db.audit_list(limit=5)
        return render_template(
            "dashboard_admin.html",
            stats=db.stats(),
            expired=expired,
            expiring_today=expiring_today,
            operations=operations,
            actions=actions,
        )

    _, my_operations = db.operations_log(
        limit=RECENT_OPERATIONS, user_id=g.user["id"], date_from=today()
    )
    return render_template(
        "dashboard_employee.html",
        expired=expired,
        expiring_today=expiring_today,
        my_operations=my_operations,
    )


@bp.get("/defrost")
def defrost():
    query, items = _search(get_db().freezer_items(), "product_name")
    for item in items:
        days = item["fridge_storage_time"]
        item["expires"] = (
            (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            if days else None
        )
    return render_template(
        "defrost.html", query=query, page=paginate(items, page_arg())
    )


@bp.post("/defrost")
def defrost_post():
    db = get_db()
    product = db.get_freezer_product_by_id(
        parse_positive_int(request.form.get("product_id")) or 0
    )
    if product is None:
        flash("Этого продукта уже нет в морозильнике.", "error")
        return _back("main.defrost")

    quantity = _form_quantity()
    if quantity is None:
        flash("Введите количество — целое число больше нуля.", "error")
        return _back("main.defrost")
    if quantity > product["quantity"]:
        flash(
            f"В морозильнике только {product['quantity']} шт. "
            f"«{product['product_name']}».", "error",
        )
        return _back("main.defrost")

    try:
        batch = db.move_to_fridge(
            product["product_name"], quantity, user_id=g.user["id"]
        )
    except ValueError as error:
        flash(str(error), "error")
        return _back("main.defrost")

    flash(
        f"Добавлено: {batch['product_name']} — {batch['quantity']} шт\n"
        f"Дата разморозки: {datetime.now():%d.%m.%Y %H:%M}\n"
        f"Годен до: {format_date(batch['expiration_date'])}",
        "success",
    )
    return _back("main.defrost")


@bp.get("/delivery")
def delivery():
    query, items = _search(get_db().catalog(), "name")
    return render_template(
        "delivery.html", query=query, page=paginate(items, page_arg())
    )


@bp.post("/delivery")
def delivery_post():
    db = get_db()
    product = db.get_product_by_id(
        parse_positive_int(request.form.get("product_id")) or 0
    )
    if product is None:
        flash("Этого товара уже нет в справочнике.", "error")
        return _back("main.delivery")

    quantity = _form_quantity(MAX_QUANTITY)
    if quantity is None:
        flash(
            f"Введите количество — целое число от 1 до {MAX_QUANTITY}.", "error"
        )
        return _back("main.delivery")

    db.new_delivery(product["name"], quantity, user_id=g.user["id"])
    in_freezer = db.get_freezer_product(product["name"])["quantity"]
    flash(
        f"В морозильник добавлено: {product['name']} — {quantity} шт\n"
        f"Теперь в морозильнике: {in_freezer} шт",
        "success",
    )
    return _back("main.delivery")


@bp.get("/expiring")
def expiring():
    expired, expiring_today = _expiring()
    return render_template(
        "expiring.html",
        expired=expired,
        expiring_today=expiring_today,
        expired_totals=sum_by_product(expired),
        today_totals=sum_by_product(expiring_today),
    )


@bp.post("/expiring/clear")
def expiring_clear():
    result = get_db().clear_expired_product(user_id=g.user["id"])
    if result is False:
        flash("Просроченных партий и партий с истекающим сегодня сроком нет.", "info")
    else:
        flash(result, "success")
    return redirect(url_for("main.expiring"))


@bp.get("/write-off")
def write_off():
    query, batches = _search(get_db().fridge_batches_list(), "product_name")
    return render_template(
        "write_off.html", query=query, page=paginate(batches, page_arg())
    )


@bp.route("/write-off/<int:batch_id>", methods=["GET", "POST"])
def write_off_batch(batch_id: int):
    db = get_db()
    batch = db.get_fridge_batch(batch_id)
    if batch is None:
        flash("Этой партии уже нет: её списали или продали полностью.", "error")
        return redirect(url_for("main.write_off"))

    if request.method == "GET":
        return render_template(
            "write_off_batch.html", batch=batch, reasons=WRITE_OFF_REASONS
        )

    operation_type = request.form.get("operation")
    if operation_type not in ("write_off", "sale"):
        abort(400)

    reason = None
    if operation_type == "write_off":
        code = request.form.get("reason", "")
        if code == "other":
            reason = clean_name(request.form.get("reason_text"))
            if not reason:
                flash("Напишите причину списания.", "error")
                return redirect(url_for("main.write_off_batch", batch_id=batch_id))
            if len(reason) > MAX_REASON_LENGTH:
                flash(
                    f"Слишком длинная причина. Уложитесь в {MAX_REASON_LENGTH} "
                    "символов.", "error",
                )
                return redirect(url_for("main.write_off_batch", batch_id=batch_id))
        else:
            reason = WRITE_OFF_REASONS.get(code)
            if reason is None:
                flash("Выберите причину списания.", "error")
                return redirect(url_for("main.write_off_batch", batch_id=batch_id))

    if request.form.get("whole"):
        quantity = batch["quantity"]
    else:
        quantity = parse_positive_int(request.form.get("quantity"))
    if quantity is None or quantity > batch["quantity"]:
        flash(
            f"Введите количество от 1 до {batch['quantity']} — столько в партии.",
            "error",
        )
        return redirect(url_for("main.write_off_batch", batch_id=batch_id))

    result = db.clear_expired_product(
        id=batch_id,
        quantity=quantity,
        operation_type=operation_type,
        user_id=g.user["id"],
        reason=reason,
    )
    if result is False:
        flash("Не получилось: партия уже закрыта или в ней меньше товара.", "error")
    else:
        flash(result, "success")
    return redirect(url_for("main.write_off"))


@bp.get("/stock")
def stock():
    db = get_db()
    query, batches = _search(db.fridge_batches_list(), "product_name")
    _, freezer = _search(db.freezer_items(), "product_name")
    groups = {"fresh": [], "today": [], "expired": []}
    for batch in batches:
        groups[batch_status(batch["expiration_date"])].append(batch)
    return render_template(
        "stock.html", query=query, groups=groups, freezer=freezer
    )


@bp.get("/history")
def history():
    page = page_arg()
    total, records = get_db().operations_log(
        page=page, limit=PAGE_SIZE, operation_type="write_off"
    )
    return render_template(
        "history.html", page=make_page(total, records, page, PAGE_SIZE)
    )
