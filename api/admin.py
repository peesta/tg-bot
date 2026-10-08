"""Разделы администратора: товары, сотрудники, Google Таблица, копии базы."""
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from api.auth import password_error
from api.deps import admin_user, get_accounts, get_db, get_settings
from storage import google_sheets, queries, table_editor
from storage.accounts import Accounts
from storage.db import Database
from storage.google_sheets import GoogleSheetsError, ImportDataError


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_user)])

MAX_NAME_LENGTH = 60
MAX_STORAGE_DAYS = 365
MAX_FREEZER_DAYS = 3650
MAX_USERNAME_LENGTH = 32
BACKUP_NAME = re.compile(r"^[\w.-]+\.db$")
# Экспорт и импорт не должны идти одновременно.
sync_lock = threading.Lock()


def clean_name(text: str | None) -> str:
    return " ".join((text or "").split())


# ---------- Товары ----------

class ProductForm(BaseModel):
    name: str
    fridge_storage_time: int
    freezer_storage_time: int | None = None
    category: str | None = None


def _validate_product(db: Database, form: ProductForm, ignore_id: int | None = None) -> dict:
    """Проверяет форму товара. «Медовик» и «медовик» — один товар;
    редактируемому товару можно поменять регистр букв (ignore_id)."""
    name = clean_name(form.name)
    if not name:
        raise ValueError("Укажите название товара")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Название — не длиннее {MAX_NAME_LENGTH} символов")
    for product in queries.catalog(db):
        if product["name"].casefold() == name.casefold() and product["id"] != ignore_id:
            raise ValueError(f"Товар «{product['name']}» уже есть в справочнике")
    if not 1 <= form.fridge_storage_time <= MAX_STORAGE_DAYS:
        raise ValueError(f"Срок после разморозки — от 1 до {MAX_STORAGE_DAYS} дней")
    if form.freezer_storage_time is not None and not 1 <= form.freezer_storage_time <= MAX_FREEZER_DAYS:
        raise ValueError(f"Срок в морозильнике — от 1 до {MAX_FREEZER_DAYS} дней или пусто")
    category = clean_name(form.category) or None
    if category and len(category) > MAX_NAME_LENGTH:
        raise ValueError(f"Категория — не длиннее {MAX_NAME_LENGTH} символов")
    return {
        "name": name,
        "fridge_storage_time": form.fridge_storage_time,
        "freezer_storage_time": form.freezer_storage_time,
        "category": category,
    }


def _product(db: Database, product_id: int) -> dict:
    product = db.get_product_by_id(product_id)
    if product is None:
        raise HTTPException(404, "Этого товара уже нет в справочнике")
    return product


@router.get("/products")
def products(db: Database = Depends(get_db)):
    return queries.catalog(db)


@router.post("/products")
def product_add(form: ProductForm, user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    values = _validate_product(db, form)
    db.new_product(values["name"], values["fridge_storage_time"], user_id=user["id"])
    product = db.get_product(values["name"])
    extra = {
        key: values[key] for key in ("freezer_storage_time", "category") if values[key] is not None
    }
    if extra:
        table_editor.update_row(db, table_editor.TABLES["products"], product["id"], extra, user)
    return product


@router.put("/products/{product_id}")
def product_edit(product_id: int, form: ProductForm,
                 user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    product = _product(db, product_id)
    values = _validate_product(db, form, ignore_id=product_id)
    renamed = values["name"] != product["name"]
    # edit_product переносит новое название на остатки и пишет журнал.
    if (
        renamed
        or values["fridge_storage_time"] != product["fridge_storage_time"]
        or (
            values["freezer_storage_time"] is not None
            and values["freezer_storage_time"] != product["freezer_storage_time"]
        )
    ):
        db.edit_product(
            product["name"], values["fridge_storage_time"],
            freezer_storage_time=values["freezer_storage_time"],
            new_name=values["name"] if renamed else None,
            user_id=user["id"],
        )
    # Очистить срок в морозильнике и сменить категорию edit_product не умеет.
    table_editor.update_row(
        db, table_editor.TABLES["products"], product_id,
        {
            "freezer_storage_time": values["freezer_storage_time"],
            "category": values["category"],
        },
        user,
    )
    return db.get_product_by_id(product_id)


@router.delete("/products/{product_id}")
def product_delete(product_id: int, user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    product = _product(db, product_id)
    db.delete_product(product["name"], user_id=user["id"])
    return {"ok": True}


# ---------- Сотрудники ----------

class NewUserForm(BaseModel):
    full_name: str
    username: str
    password: str
    role: str


class UserUpdate(BaseModel):
    full_name: str | None = None
    username: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None


def _check_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise ValueError("Укажите логин")
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValueError(f"Логин — не длиннее {MAX_USERNAME_LENGTH} символов")
    if not all(char.isalnum() or char in "._-" for char in username):
        raise ValueError("В логине можно использовать буквы, цифры и символы . _ -")
    return username


def _check_full_name(full_name: str) -> str:
    full_name = clean_name(full_name)
    if not 0 < len(full_name) <= MAX_NAME_LENGTH:
        raise ValueError(f"Имя — от 1 до {MAX_NAME_LENGTH} символов")
    return full_name


def _check_role(role: str) -> str:
    if role not in table_editor.ROLE_TITLES:
        raise ValueError("Выберите роль")
    return role


@router.get("/users")
def users(accounts: Accounts = Depends(get_accounts)):
    return accounts.users()


@router.post("/users")
def user_add(form: NewUserForm, user: dict = Depends(admin_user),
             accounts: Accounts = Depends(get_accounts)):
    full_name = _check_full_name(form.full_name)
    username = _check_username(form.username)
    role = _check_role(form.role)
    error = password_error(form.password)
    if error:
        raise ValueError(error)
    user_id = accounts.create_user(full_name, username, form.password, role, created_by=user["id"])
    return {"id": user_id}


@router.patch("/users/{user_id}")
def user_update(user_id: int, form: UserUpdate, user: dict = Depends(admin_user),
                db: Database = Depends(get_db), accounts: Accounts = Depends(get_accounts)):
    person = accounts.get(user_id)
    if person is None:
        raise HTTPException(404, "Такого сотрудника нет")

    is_self = user_id == user["id"]
    if is_self and form.role is not None and form.role != person["role"]:
        raise ValueError("Нельзя лишить себя прав: свою роль меняет другой администратор")
    if is_self and form.is_active is False:
        raise ValueError("Нельзя отключить доступ самому себе")

    # Сначала всё проверяем, потом меняем: ошибка не оставит правку наполовину.
    full_name = _check_full_name(form.full_name) if form.full_name is not None else None
    username = _check_username(form.username) if form.username is not None else None
    role = _check_role(form.role) if form.role is not None else None
    if form.password is not None and password_error(form.password):
        raise ValueError(password_error(form.password))
    if username is not None and accounts.username_taken(username, except_user_id=user_id):
        raise ValueError(f"Логин «{username}» уже занят")
    if person["username"] is None and username is not None and form.password is None:
        raise ValueError("Задайте пароль: у сотрудника ещё нет учётной записи")
    if person["username"] is None and username is None and form.password is not None:
        raise ValueError("Задайте логин: у сотрудника ещё нет учётной записи")

    if full_name is not None and full_name != person["full_name"]:
        table_editor.update_row(
            db, table_editor.TABLES["users"], user_id, {"full_name": full_name}, user
        )
    if role is not None and role != person["role"]:
        db.set_user_role(user_id, role, changed_by=user["id"])
    if form.is_active is not None and form.is_active != person["is_active"]:
        db.set_user_active(user_id, form.is_active, changed_by=user["id"])
    if username is not None or form.password is not None:
        accounts.set_login(
            user_id, username or person["username"], form.password, changed_by=user["id"]
        )
    return {key: value for key, value in accounts.get(user_id).items() if key != "password_hash"}


# ---------- Google Таблица ----------

def _google_settings(settings: dict) -> dict:
    table = settings["google_table"]
    credentials_file = settings["credentials_file"]
    has_credentials = Path(credentials_file).is_file()
    return {
        "table": table,
        "url": google_sheets.spreadsheet_url(table) if table else None,
        "credentials_file": credentials_file,
        "has_credentials": has_credentials,
        "email": (
            google_sheets._service_account_email(credentials_file) if has_credentials else None
        ),
        # Названия листов: {"products": "Товары", …}
        "sheets": google_sheets.SHEET_TITLES,
    }


@router.get("/google")
def google(settings: dict = Depends(get_settings)):
    return _google_settings(settings)


@router.post("/google/{action}")
def google_sync(action: str, user: dict = Depends(admin_user),
                db: Database = Depends(get_db), settings: dict = Depends(get_settings)):
    if action not in ("export", "import"):
        raise HTTPException(404, "Нет такого действия")
    if not sync_lock.acquire(blocking=False):
        raise ValueError("Уже идёт экспорт или импорт. Подождите и попробуйте снова")

    title = "Экспорт" if action == "export" else "Импорт"
    try:
        if action == "export":
            counts = google_sheets.export_to_google(
                db, settings["google_table"], settings["credentials_file"]
            )
            db.log_change("google_export", ", ".join(
                f"{google_sheets.SHEET_TITLES[table]}: {count}" for table, count in counts.items()
            ), user["id"])
            return {"counts": counts}
        counts, backup = google_sheets.import_from_google(
            db, settings["google_table"], settings["credentials_file"], user_id=user["id"]
        )
        return {"counts": counts, "backup": backup}
    except ImportDataError as error:
        db.log_error("ImportDataError", "\n".join(error.errors))
        return JSONResponse(
            {"detail": "Импорт не выполнен, база не изменена", "errors": error.errors},
            status_code=400,
        )
    except GoogleSheetsError as error:
        db.log_error("GoogleSheetsError", str(error))
        suffix = ", база не изменена" if action == "import" else ""
        return JSONResponse({"detail": f"{title} не выполнен{suffix}. {error}"}, status_code=400)
    finally:
        sync_lock.release()


# ---------- Резервные копии ----------

def _backup_dir(db: Database) -> Path:
    return Path(db.path_to_db).parent / "backups"


def _backup_path(db: Database, name: str) -> Path:
    path = _backup_dir(db) / name
    if not BACKUP_NAME.match(name) or not path.is_file():
        raise HTTPException(404, "Такой копии нет")
    return path


def _make_backup(db: Database, prefix: str) -> str:
    name = f"{prefix}_{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
    db.backup(str(_backup_dir(db) / name))
    return name


@router.get("/backups")
def backups(db: Database = Depends(get_db)):
    files = []
    if _backup_dir(db).is_dir():
        for path in _backup_dir(db).glob("*.db"):
            stat = path.stat()
            files.append({
                "name": path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    files.sort(key=lambda file: file["created_at"], reverse=True)
    return files


@router.post("/backups")
def backup_create(user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    name = _make_backup(db, "manual")
    db.log_change("backup_created", name, user["id"])
    return {"name": name}


@router.get("/backups/{name}")
def backup_download(name: str, db: Database = Depends(get_db)):
    path = _backup_path(db, name)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


def _keep_logs(db: Database, saved_path: Path) -> None:
    """Журналы не откатываются вместе с базой: записи, сделанные после
    копии, переносятся из базы, сохранённой перед восстановлением.
    Сессии тоже берутся из неё: восстановление не выкидывает вошедших
    и не возвращает сессии, закрытые кнопкой «Выйти»."""
    connection = sqlite3.connect(db.path_to_db)
    try:
        connection.execute("ATTACH DATABASE ? AS saved", (str(saved_path),))
        for table in ("change_log", "errors"):
            main_columns = {row[1] for row in connection.execute(f"PRAGMA main.table_info({table})")}
            saved_columns = [row[1] for row in connection.execute(f"PRAGMA saved.table_info({table})")]
            names = ", ".join(name for name in saved_columns if name in main_columns)
            if not names:
                continue
            connection.execute(
                f"INSERT INTO main.{table} ({names}) SELECT {names} FROM saved.{table} "
                f"WHERE id > (SELECT COALESCE(MAX(id), 0) FROM main.{table})"
            )
        connection.execute("DELETE FROM main.sessions")
        connection.execute(
            "INSERT INTO main.sessions (token_hash, user_id, last_seen) "
            "SELECT token_hash, user_id, last_seen FROM saved.sessions"
        )
        connection.commit()
        connection.execute("DETACH DATABASE saved")
    finally:
        connection.close()


@router.post("/backups/{name}/restore")
def backup_restore(name: str, user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    path = _backup_path(db, name)
    source = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        try:
            source.execute("SELECT name FROM sqlite_master").fetchall()
        except sqlite3.DatabaseError as error:
            raise ValueError(f"Файл {name} не похож на базу данных: {error}") from None
        saved = _make_backup(db, "before_restore")
        target = sqlite3.connect(db.path_to_db)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    # Копия может быть старой: создаём недостающие таблицы и учётные записи.
    Database(db.path_to_db)
    accounts = Accounts(db)
    _keep_logs(db, _backup_dir(db) / saved)
    accounts.create_defaults()
    db.log_change("backup_restored", f"{name} (база до восстановления — {saved})", user["id"])
    return {"saved": saved}


@router.delete("/backups/{name}")
def backup_delete(name: str, user: dict = Depends(admin_user), db: Database = Depends(get_db)):
    _backup_path(db, name).unlink()
    db.log_change("backup_deleted", name, user["id"])
    return {"ok": True}
