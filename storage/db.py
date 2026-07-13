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
    
    def new_fridge_product(self, product_name: str, quantity: int):
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
    
    def expire_product(self):
        with self.cursor() as cursor:
            today = datetime.now()
            cursor.execute("""
                SELECT id, product_name, quantity, expiration_date FROM fridge WHERE expiration_date <= ?
            """, (today.strftime("%Y-%m-%d"),))
            products = cursor.fetchall()

            if products is None:
                return False

            expired_products = []
            expire_today = []
            for product in products:
                if product[3] < today.strftime("%Y-%m-%d"):
                    expired_products.append(f'{product[0]} - {product[1]} шт.')
                elif product[3] == today.strftime("%Y-%m-%d"):
                    expire_today.append(f'{product[0]} - {product[1]} шт.')
            return expired_products, expire_today

    def clear_expired_product(self,id, quantity: int):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT quantity FROM fridge WHERE id = ?
            """, (id,))
            row = cursor.fetchall
            if row is None:
                return False
            fridge_quantity = row[0]
            if fridge_quantity - quantity < 0:
                return False
            elif fridge_quantity - quantity > 0:
                cursor.execute("""
                    UPDATE fridge SET quantity = ? WHERE id = ?
                """, (quantity, id))
            else: 
                cursor.execute("""
                    DELETE FROM fridge WHERE id = ?
                """, (id,))

    def new_delivery(self, product_name: str, quantity: int):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT quantity FROM feezer WHERE product_name = ?
            """, (product_name,))

            row = cursor.fetchall()
            if row is None:
                cursor.execute("""
                    INSERT INTO freezer (product_name, quantity)
                    VALUES (?, ?)
                """, (product_name, quantity))

                return (f'Успешно добавлено {quantity} {product_name} в морозильник')

            else:
                cursor.execute("""
                    UPDATE freezer SET quantity = ? WHERE product_name = ?
                """, (quantity + row[0], product_name))
                return (f'Успешно добавлено {quantity} {product_name} в морозильник')

    

            


    