"""Общие зависимости обработчиков: база, учётные записи, текущий сотрудник."""
import hashlib
import secrets

from fastapi import Depends, HTTPException, Request

from storage.accounts import Accounts
from storage.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_accounts(request: Request) -> Accounts:
    return request.app.state.accounts


def get_settings(request: Request) -> dict:
    return request.app.state.settings


def session_token(user: dict) -> str:
    """Отпечаток пароля для сессии: после смены пароля вход на других
    устройствах перестаёт действовать."""
    return hashlib.sha256(user["password_hash"].encode()).hexdigest()[:16]


def current_user(request: Request, accounts: Accounts = Depends(get_accounts)) -> dict:
    """Вошедший сотрудник. Отключённого, сменившего пароль или нажавшего
    «Выйти» (сессия удалена из базы) сразу выкидывает с сайта."""
    user_id = request.session.get("user_id")
    user = accounts.get(user_id) if user_id is not None else None
    if (
        user is None
        or accounts.session_user_id(request.session.get("sid")) != user["id"]
        or not user["is_active"]
        or not user["password_hash"]
        or not secrets.compare_digest(
            request.session.get("auth", ""), session_token(user)
        )
    ):
        request.session.clear()
        raise HTTPException(401, "Войдите на сайт")
    # По нему обработчики ошибок отличают сотрудников от анонимных запросов.
    request.state.user = user
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Этот раздел доступен только администратору")
    return user


def public_user(user: dict) -> dict:
    """Сотрудник для ответа браузеру — без хеша пароля."""
    return {
        key: user[key]
        for key in ("id", "full_name", "role", "is_active", "username", "last_login")
    }
