import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

class Database:
    def _init_db(self, path_to_db="data/database.db"):
        conn = self.get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                name TEXT PRIMARY KEY,
                fridge_storage_time INTEGER,
                freezer_storage_time INTEGER,
                category TEXT
            )
        """)
        conn.execute("""
            CRATE TABLE IF NOT EXISTS fridge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT,
                quantity INTEGER,
                date_added TEXT NOT NULL,
                expiration_date TEXT NOT NULL
            )
        """)
        conn.execute("""
            CRATE TABLE IF NOT EXISTS freezer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT,
                quantity INTEGER,
                date_added TEXT NOT NULL,
                expiration_date TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def get_conn(self):
        conn = sqlite3.connect("storage/users.db")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def cursor(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def new_delivery(self, product_name: str, quantity: int):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT fridge_storage_time FROM products WHERE name = ?
            """, (product_name))
            fridge_storage_time = cursor.fetchone()[0]
            cursor.execute("""
                INSERT INTO fridge (product_name, quantity, date_added, expiration_date)
                VALUES (?, ?, ?, ?)
            """, (product_name, quantity, datetime.now().strftime("%Y-%m-%d %H:%M"), datetime.now().strftime("%Y-%m-%d %H:%M") + timedelta(days=fridge_storage_time)))
            return (f'Успешно добавлено {quantity} {product_name} в холодильник')
    
    def expire_product(self, product_name: str):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT product_name, quantity, expiration_date FROM fridge WHERE expiration_date <= ? AND product_name = ?
            """, (datetime.now().strftime("%Y-%m-%d %H:%M"), product_name))
            products = cursor.fetchall()
            expired_products = []
            expire_today = []
            for product in products:
                if product[2] < datetime.now().strftime("%Y-%m-%d %H:%M"):
                    expired_products.append(f'{product[0]} - {product[1]} шт.')
                elif product[2] == datetime.now().strftime("%Y-%m-%d %H:%M"):
                    expire_today.append(f'{product[0]} - {product[1]} шт.')
            return (f'Просроченные продукты: {expired_products}, Продукты, которые просрочатся сегодня: {expire_today}')

