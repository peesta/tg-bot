"""Разделы администратора: товары, сотрудники, Google Таблица, копии базы."""
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, send_from_directory, url_for,
)
from werkzeug.utils import secure_filename

from storage import google_sheets
from storage.google_sheets import GoogleSheetsError, ImportDataError
from web.auth import (
    hash_password, password_error, require_admin, username_error,
)
from web.utils import (
    MAX_NAME_LENGTH, MAX_STORAGE_DAYS, ROLE_TITLES, audit,
    clean_name, get_db, matches, page_arg, paginate, parse_positive_int,
)


bp = Blueprint("admin", __name__, url_prefix="/admin")
bp.before_request(require_admin)

MAX_FREEZER_DAYS = 3650
SHEET_TITLES = {
    "products": "товары",
    "freezer": "морозильник",
    "fridge": "партии холодильника",
}
# Экспорт и импорт не должны идти одновременно.
sync_lock = threading.Lock()


# ---------- Товары ----------

def _product_form() -> dict:
    return {
        "name": clean_name(request.form.get("name")),
        "fridge_storage_time": request.form.get("fridge_storage_time", "").strip(),
        "freezer_storage_time": request.form.get("freezer_storage_time", "").strip(),
        "category": clean_name(request.form.get("category")),
    }


def _validate_product(form: dict, ignore_id: int | None = None) -> tuple[dict | None, str | None]:
    """Проверяет форму товара: (значения для базы, None) или (None, ошибка).

    «Медовик» и «медовик» считаются одним товаром. ignore_id — товар,
    который редактируют: ему можно поменять регистр букв.
    """
    name = form["name"]
    if not name:
        return None, "Укажите название товара."
    if len(name) > MAX_NAME_LENGTH:
        return None, f"Слишком длинное название. Уложитесь в {MAX_NAME_LENGTH} символов."
    for product in get_db().catalog():
        if product["name"].casefold() == name.casefold() and product["id"] != ignore_id:
            return None, f"Товар «{product['name']}» уже есть в справочнике."

    fridge_days = parse_positive_int(form["fridge_storage_time"], MAX_STORAGE_DAYS)
    if fridge_days is None:
        return None, (
            "Срок хранения после разморозки — целое число дней "
            f"от 1 до {MAX_STORAGE_DAYS}."
        )

    freezer_days = None
    if form["freezer_storage_time"]:
        freezer_days = parse_positive_int(form["freezer_storage_time"], MAX_FREEZER_DAYS)
        if freezer_days is None:
            return None, (
                "Срок хранения в морозильнике — целое число дней "
                f"от 1 до {MAX_FREEZER_DAYS} или пустое поле."
            )

    if len(form["category"]) > MAX_NAME_LENGTH:
        return None, f"Слишком длинная категория. Уложитесь в {MAX_NAME_LENGTH} символов."

    return {
        "name": name,
        "fridge_storage_time": fridge_days,
        "freezer_storage_time": freezer_days,
        "category": form["category"] or None,
    }, None


def _products_page(form: dict | None = None, error: str | None = None):
    query = request.args.get("q", "").strip()
    products = get_db().catalog()
    if query:
        products = [
            product for product in products
            if matches(product["name"], query) or matches(product["category"], query)
        ]
    return render_template(
        "admin/products.html",
        query=query,
        page=paginate(products, page_arg()),
        form=form or {},
        error=error,
    )


@bp.get("/products")
def products():
    return _products_page()


@bp.post("/products")
def product_add():
    form = _product_form()
    values, error = _validate_product(form)
    if error:
        return _products_page(form, error), 400

    try:
        get_db().new_product(
            values["name"], values["fridge_storage_time"],
            values["freezer_storage_time"], values["category"],
        )
    except ValueError as db_error:
        return _products_page(form, str(db_error)), 400

    audit(
        "product_created",
        f"{values['name']}: {values['fridge_storage_time']} дн. после разморозки",
    )
    flash(f"Товар «{values['name']}» добавлен.", "success")
    return redirect(url_for("admin.products"))


@bp.route("/products/<int:product_id>", methods=["GET", "POST"])
def product_edit(product_id: int):
    db = get_db()
    product = db.get_product_by_id(product_id)
    if product is None:
        flash("Этого товара уже нет в справочнике.", "error")
        return redirect(url_for("admin.products"))

    in_freezer = db.get_freezer_product(product["name"])
    if request.method == "GET":
        form = {
            key: "" if product[key] is None else product[key]
            for key in ("name", "fridge_storage_time", "freezer_storage_time", "category")
        }
        return render_template(
            "admin/product_form.html", product=product, form=form,
            in_freezer=in_freezer,
        )

    form = _product_form()
    values, error = _validate_product(form, ignore_id=product_id)
    if error is None:
        try:
            db.update_product(
                product["name"], values["name"], values["fridge_storage_time"],
                values["freezer_storage_time"], values["category"],
            )
        except ValueError as db_error:
            error = str(db_error)
    if error:
        return render_template(
            "admin/product_form.html", product=product, form=form,
            in_freezer=in_freezer, error=error,
        ), 400

    changes = [
        f"{key}: {product[key]} → {values[key]}"
        for key in values if product[key] != values[key]
    ]
    if changes:
        audit("product_updated", f"{product['name']}: " + "; ".join(changes))
    flash(
        "Товар сохранён. Новый срок хранения применяется к новым разморозкам, "
        "у уже размороженных партий срок не меняется.",
        "success",
    )
    return redirect(url_for("admin.product_edit", product_id=product_id))


@bp.post("/products/<int:product_id>/delete")
def product_delete(product_id: int):
    db = get_db()
    product = db.get_product_by_id(product_id)
    if product is None:
        flash("Этого товара уже нет в справочнике.", "error")
        return redirect(url_for("admin.products"))

    try:
        db.delete_product(product["name"])
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.product_edit", product_id=product_id))

    audit("product_deleted", product["name"])
    flash(f"Товар «{product['name']}» удалён. История операций сохранилась.", "success")
    return redirect(url_for("admin.products"))


# ---------- Сотрудники ----------

def _users_page(form: dict | None = None, error: str | None = None):
    return render_template(
        "admin/users.html",
        users=get_db().users_list(),
        form=form or {"role": "employee"},
        error=error,
    )


@bp.get("/users")
def users():
    return _users_page()


@bp.post("/users")
def user_add():
    form = {
        "username": request.form.get("username", "").strip(),
        "full_name": clean_name(request.form.get("full_name")),
        "role": request.form.get("role", ""),
    }
    password = request.form.get("password", "")
    error = username_error(form["username"])
    if error is None and not form["full_name"]:
        error = "Укажите имя сотрудника."
    elif error is None and len(form["full_name"]) > MAX_NAME_LENGTH:
        error = f"Имя должно быть не длиннее {MAX_NAME_LENGTH} символов."
    elif error is None and form["role"] not in ROLE_TITLES:
        error = "Выберите роль."
    if error is None:
        error = password_error(password, password)
    if error:
        return _users_page(form, error), 400

    try:
        user_id = get_db().add_user(
            form["username"], form["full_name"], hash_password(password),
            form["role"],
        )
    except ValueError as db_error:
        return _users_page(form, str(db_error)), 400

    audit(
        "user_created",
        f"{form['username']} ({form['full_name']}), роль: {ROLE_TITLES[form['role']]}",
    )
    flash(
        f"{form['full_name']} может входить на сайт с логином «{form['username']}».",
        "success",
    )
    return redirect(url_for("admin.user_edit", user_id=user_id))


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
def user_edit(user_id: int):
    db = get_db()
    user = db.get_user(user_id)
    if user is None:
        flash("Такого пользователя нет.", "error")
        return redirect(url_for("admin.users"))

    is_self = user_id == g.user["id"]
    if request.method == "GET":
        return render_template("admin/user.html", person=user, is_self=is_self)

    action = request.form.get("action")
    error, details = None, None
    if action == "profile":
        full_name = clean_name(request.form.get("full_name"))
        username = request.form.get("username", "").strip()
        error = username_error(username)
        if error is None and not 0 < len(full_name) <= MAX_NAME_LENGTH:
            error = f"Имя должно быть от 1 до {MAX_NAME_LENGTH} символов."
        if error is None:
            try:
                db.set_user_username(user_id, username)
                db.set_user_name(user_id, full_name)
            except ValueError as db_error:
                error = str(db_error)
            details = (
                f"{user['username']}: логин → {username}, имя → {full_name}"
            )
    elif action in ("role", "access"):
        if is_self:
            error = "Свою роль и доступ изменить нельзя."
        elif action == "role":
            role = request.form.get("role")
            if role not in ROLE_TITLES:
                abort(400)
            db.set_user_role(user_id, role)
            details = f"{user['username']}: роль → {ROLE_TITLES[role]}"
        else:
            is_active = request.form.get("is_active") == "1"
            db.set_user_active(user_id, is_active)
            details = (
                f"{user['username']}: доступ "
                f"{'включён' if is_active else 'отключён'}"
            )
    elif action == "password":
        password = request.form.get("password", "")
        error = password_error(password, password)
        if error is None:
            db.set_user_password(user_id, hash_password(password))
            details = f"{user['username']}: задан новый пароль"
    else:
        abort(400)

    if error:
        flash(error, "error")
    else:
        audit("user_updated", details)
        flash("Сохранено.", "success")
    return redirect(url_for("admin.user_edit", user_id=user_id))


# ---------- Google Таблица ----------

def _google_settings() -> dict:
    table = current_app.config.get("GOOGLE_TABLE")
    credentials_file = current_app.config["CREDENTIALS_FILE"]
    has_credentials = Path(credentials_file).is_file()
    return {
        "table": table,
        "url": google_sheets.spreadsheet_url(table) if table else None,
        "credentials_file": credentials_file,
        "has_credentials": has_credentials,
        "email": (
            google_sheets._service_account_email(credentials_file)
            if has_credentials else None
        ),
    }


@bp.get("/google")
def google():
    return render_template("admin/google.html", settings=_google_settings())


@bp.post("/google/<action>")
def google_sync(action: str):
    if action not in ("export", "import"):
        abort(404)

    settings = _google_settings()
    result = {"action": action}
    if not sync_lock.acquire(blocking=False):
        result["error"] = "Уже идёт экспорт или импорт. Подождите и попробуйте снова."
        return render_template(
            "admin/google.html", settings=settings, result=result,
            sheet_titles=SHEET_TITLES,
        )

    try:
        if action == "export":
            result["counts"] = google_sheets.export_to_google(
                get_db(), settings["table"], settings["credentials_file"]
            )
        else:
            result["counts"], result["backup"] = google_sheets.import_from_google(
                get_db(), settings["table"], settings["credentials_file"]
            )
    except ImportDataError as error:
        result["errors"] = error.errors
    except GoogleSheetsError as error:
        result["error"] = str(error)
    finally:
        sync_lock.release()

    if "counts" in result:
        audit(
            f"google_{action}",
            ", ".join(f"{title}: {count}" for title, count in result["counts"].items()),
        )
    return render_template(
        "admin/google.html", settings=settings, result=result,
        sheet_titles=SHEET_TITLES,
    )


# ---------- Резервные копии ----------

def _backup_dir() -> Path:
    return Path(get_db().path_to_db).parent / "backups"


def _backup_path(name: str) -> Path:
    """Путь к копии по имени файла; чужие пути и несуществующие файлы — 404."""
    if name != secure_filename(name) or not name.endswith(".db"):
        abort(404)
    path = _backup_dir() / name
    if not path.is_file():
        abort(404)
    return path


def _make_backup(prefix: str) -> str:
    name = f"{prefix}_{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
    get_db().backup(str(_backup_dir() / name))
    return name


@bp.get("/backups")
def backups():
    files = []
    if _backup_dir().is_dir():
        for path in _backup_dir().glob("*.db"):
            stat = path.stat()
            files.append({
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
            })
    files.sort(key=lambda file: file["modified"], reverse=True)
    return render_template("admin/backups.html", files=files)


@bp.post("/backups")
def backup_create():
    name = _make_backup("manual")
    audit("backup_created", name)
    flash(f"Копия базы сохранена: {name}", "success")
    return redirect(url_for("admin.backups"))


@bp.get("/backups/<name>")
def backup_download(name: str):
    path = _backup_path(name)
    return send_from_directory(path.parent.resolve(), path.name, as_attachment=True)


@bp.post("/backups/<name>/restore")
def backup_restore(name: str):
    path = _backup_path(name)
    saved = _make_backup("before_restore")
    try:
        get_db().restore(str(path))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.backups"))

    audit("backup_restored", f"{name} (текущая база сохранена в {saved})")
    flash(
        f"База восстановлена из копии {name}. Состояние до восстановления "
        f"сохранено в {saved}.",
        "success",
    )
    return redirect(url_for("admin.backups"))


@bp.post("/backups/<name>/delete")
def backup_delete(name: str):
    _backup_path(name).unlink()
    audit("backup_deleted", name)
    flash(f"Копия {name} удалена.", "success")
    return redirect(url_for("admin.backups"))
