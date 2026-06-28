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
                SELECT quantity FROM freezer WHERE product_name = ?
            """, (product_name,))

            freezer_quantity = cursor.fetchone()[0]
            if freezer_quantity is not None:
                freezer_quantity -= quantity
                if freezer_quantity < 0:
                    return (f'Недостаточно {product_name} в морозильнике')
                else:
                    cursor.execute("""
                        UPDATE freezer SET quantity = ? WHERE product_name = ?
                    """, (freezer_quantity, product_name))
                    return (f'Успешно добавлено {quantity} {product_name} в холодильник')
            else:
                return (f'Недостаточно {product_name} в морозильнике')

            cursor.execute("""
                SELECT fridge_storage_time FROM products WHERE name = ?
            """, (product_name,))
            row = cursor.fetchone()
            
            if row is not None:
                return (f'Продукт {product_name} не найден')
            fridge_storage_time = row[0]

            today = datetime.now()

            date_added = today.strftime("%Y-%m-%d")
            expiration_date = (today + timedelta(days=fridge_storage_time)).strftime("%Y-%m-%d")

            cursor.execute("""
                INSERT INTO fridge (product_name, quantity, date_added, expiration_date)
                VALUES (?, ?, ?, ?)
            """, (product_name, quantity, date_added, expiration_date))

            return (f'Успешно добавлено {quantity} {product_name} в холодильник')
    
    def expire_product(self, product_name: str):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT product_name, quantity, expiration_date FROM fridge WHERE expiration_date <= ? AND product_name = ?
            """, (datetime.now().strftime("%Y-%m-%d"), product_name))
            products = cursor.fetchall()
            expired_products = []
            expire_today = []
            for product in products:
                if product[2] < datetime.now().strftime("%Y-%m-%d"):
                    expired_products.append(f'{product[0]} - {product[1]} шт.')
                elif product[2] == datetime.now().strftime("%Y-%m-%d"):
                    expire_today.append(f'{product[0]} - {product[1]} шт.')
            return (f'Просроченные продукты: {expired_products}, Продукты, которые просрочатся сегодня: {expire_today}')

    def delete_expired_products(self, any_product: bool = False):
        with self.cursor() as cursor:
            if any_product: 
                cursor.execute("""
                    DELETE FROM fridge WHERE expiration_date <= ?
                """, (datetime.now().strftime("%Y-%m-%d")))
                return (f'Просроченные продукты удалены')
            else:
                cursor.execute("""
                    DELETE FROM fridge WHERE expiration_date < ?
                """, (datetime.now().strftime("%Y-%m-%d")))