"""Логины и пароли для входа на сайт.

Сотрудники хранятся в таблице users из storage/db.py (номер, имя, роль,
доступ). Здесь — только учётные данные к ним: логин и хеш пароля.
Сотрудник без учётной записи (например, оставшийся от Telegram-бота)
войти на сайт не может, пока администратор не задаст ему логин и пароль.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from storage.db import Database


ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    last_seen TEXT NOT NULL
);
"""

# Учётные записи при первом запуске: логин, пароль, имя, роль.
DEFAULT_ACCOUNTS = (
    ("admin", "admin", "Администратор", "admin"),
    ("employee", "employee", "Сотрудник", "employee"),
)

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

# Сессия без запросов дольше этого срока закрывается.
SESSION_HOURS = 12
# last_seen обновляется не чаще, чтобы не писать в базу на каждый запрос.
SESSION_TOUCH_MINUTES = 5
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

USER_FIELDS = """
    users.telegram_id AS id, users.full_name, users.role, users.is_active,
    accounts.username, accounts.password_hash, accounts.last_login
"""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def check_password(password_hash: str | None, password: str) -> bool:
    try:
        _, n, r, p, salt, expected = (password_hash or "").split("$")
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt),
            n=int(n), r=int(r), p=int(p),
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


def _token_hash(token: str) -> str:
    """В базе (и в её копиях) хранится не сам ключ сессии, а его хеш."""
    return hashlib.sha256(token.encode()).hexdigest()


def _user(row) -> dict | None:
    if row is None:
        return None
    user = dict(row)
    user["is_active"] = bool(user["is_active"])
    return user


class Accounts:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.cursor() as cursor:
            cursor.executescript(ACCOUNTS_SCHEMA)

    def get(self, user_id: int) -> dict | None:
        """Сотрудник с логином и хешем пароля (логина может не быть)."""
        with self.db.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {USER_FIELDS}
                FROM users
                LEFT JOIN accounts ON accounts.user_id = users.telegram_id
                WHERE users.telegram_id = ?
                """,
                (user_id,),
            )
            return _user(cursor.fetchone())

    def get_by_username(self, username: str) -> dict | None:
        """Сотрудник по логину без учёта регистра или None."""
        with self.db.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {USER_FIELDS}
                FROM accounts
                JOIN users ON users.telegram_id = accounts.user_id
                WHERE accounts.username = ? COLLATE NOCASE
                """,
                (username,),
            )
            return _user(cursor.fetchone())

    def users(self) -> list[dict]:
        """Все сотрудники с логинами (без хешей): сначала администраторы."""
        with self.db.cursor() as cursor:
            cursor.execute(
                """
                SELECT users.telegram_id AS id, users.full_name, users.role,
                    users.is_active, accounts.username, accounts.last_login
                FROM users
                LEFT JOIN accounts ON accounts.user_id = users.telegram_id
                ORDER BY users.role = 'admin' DESC, users.full_name ASC
                """
            )
            return [_user(row) for row in cursor.fetchall()]

    def has_any(self) -> bool:
        with self.db.cursor() as cursor:
            cursor.execute("SELECT 1 FROM accounts LIMIT 1")
            return cursor.fetchone() is not None

    def username_taken(self, username: str, except_user_id: int | None = None) -> bool:
        user = self.get_by_username(username)
        return user is not None and user["id"] != except_user_id

    def _next_user_id(self) -> int:
        """Номер для нового сотрудника. 0 занят системой (SYSTEM_USER_ID)."""
        with self.db.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(telegram_id), 0) + 1 FROM users")
            return max(int(cursor.fetchone()[0]), 1)

    def create_user(
        self,
        full_name: str,
        username: str,
        password: str,
        role: str,
        created_by: int | None = None,
    ) -> int:
        """Добавляет сотрудника с логином и паролем, возвращает его номер."""
        if self.username_taken(username):
            raise ValueError(f"Логин «{username}» уже занят")
        user_id = self._next_user_id()
        self.db.add_user(user_id, full_name, role, created_by=created_by)
        self.set_login(user_id, username, password, changed_by=created_by)
        return user_id

    def set_login(
        self,
        user_id: int,
        username: str,
        password: str | None = None,
        changed_by: int | None = None,
    ) -> None:
        """Задаёт логин и, если передан, пароль. Сотруднику без учётной
        записи пароль обязателен."""
        if self.username_taken(username, except_user_id=user_id):
            raise ValueError(f"Логин «{username}» уже занят")
        current = self.get(user_id)
        if current is None:
            raise ValueError(f"Нет сотрудника № {user_id}")
        if current["username"] is None and password is None:
            raise ValueError("Задайте пароль: у сотрудника ещё нет учётной записи")

        with self.db.cursor() as cursor:
            if current["username"] is None:
                cursor.execute(
                    """
                    INSERT INTO accounts (user_id, username, password_hash)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, username, hash_password(password)),
                )
                details = f"№ {user_id}: создана учётная запись «{username}»"
            else:
                cursor.execute(
                    "UPDATE accounts SET username = ? WHERE user_id = ?",
                    (username, user_id),
                )
                changes = []
                if current["username"] != username:
                    changes.append(f"логин «{current['username']}» → «{username}»")
                if password is not None:
                    cursor.execute(
                        "UPDATE accounts SET password_hash = ? WHERE user_id = ?",
                        (hash_password(password), user_id),
                    )
                    changes.append("новый пароль")
                if not changes:
                    return
                details = f"№ {user_id}: " + ", ".join(changes)
            self.db._log_change(cursor, "account_changed", details, changed_by, "accounts")

    def set_password(
        self, user_id: int, password: str, changed_by: int | None = None
    ) -> None:
        user = self.get(user_id)
        if user is None or user["username"] is None:
            raise ValueError("У сотрудника нет учётной записи")
        self.set_login(user_id, user["username"], password, changed_by)

    def delete(self, user_id: int) -> None:
        """Удаляет учётную запись (вызывается вместе с удалением сотрудника)."""
        with self.db.cursor() as cursor:
            cursor.execute("DELETE FROM accounts WHERE user_id = ?", (user_id,))

    def touch_login(self, user_id: int) -> None:
        with self.db.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET last_login = ? WHERE user_id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
            )

    # ---------- Сессии ----------

    def create_session(self, user_id: int) -> str:
        """Новая сессия после входа; возвращает ключ для cookie."""
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        with self.db.cursor() as cursor:
            cursor.execute(
                "DELETE FROM sessions WHERE last_seen < ?",
                ((now - timedelta(hours=SESSION_HOURS)).strftime(TIME_FORMAT),),
            )
            cursor.execute(
                "INSERT INTO sessions (token_hash, user_id, last_seen) VALUES (?, ?, ?)",
                (_token_hash(token), user_id, now.strftime(TIME_FORMAT)),
            )
        return token

    def session_user_id(self, token: str | None) -> int | None:
        """Сотрудник по ключу сессии или None, если сессия закрыта или
        устарела. Продлевает сессию, пока ею пользуются."""
        if not token:
            return None
        now = datetime.now()
        with self.db.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, last_seen FROM sessions WHERE token_hash = ?",
                (_token_hash(token),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            last_seen = datetime.strptime(row["last_seen"], TIME_FORMAT)
            if now - last_seen > timedelta(hours=SESSION_HOURS):
                cursor.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),)
                )
                return None
            if now - last_seen > timedelta(minutes=SESSION_TOUCH_MINUTES):
                cursor.execute(
                    "UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
                    (now.strftime(TIME_FORMAT), _token_hash(token)),
                )
            return row["user_id"]

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self.db.cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def create_defaults(self) -> bool:
        """Создаёт admin/admin и employee/employee, если войти пока некому."""
        if self.has_any():
            return False
        for username, password, full_name, role in DEFAULT_ACCOUNTS:
            if self.get_by_username(username) is None:
                self.create_user(full_name, username, password, role)
        return True
