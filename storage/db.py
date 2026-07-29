import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

class Database:
    def __init__(self, path_to_db="data/database.db"):
        self.path_to_db = path_to_db
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
            CREATE TABLE IF NOT EXISTS fridge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                date_added TEXT NOT NULL,
                expiration_date TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS freezer (
                product_name TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'employee')),
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL CHECK (operation_type IN ('delivery', 'defrost', 'sale', 'write_off')),
                product_name TEXT NOT NULL,
                batch_id INTEGER,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                reason TEXT,
                created_at TEXT NOT NULL,
                created_by INTEGER NOT NULL,

                FOREIGN KEY (batch_id) REFERENCES fridge(id),
                FOREIGN KEY (created_by) REFERENCES users(telegram_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_operations_created_at ON operations(created_at);
            CREATE INDEX IF NOT EXISTS idx_operations_created_by ON operations(created_by);
        """)
        conn.commit()
        conn.close()

    def get_conn(self):
        conn = sqlite3.connect(self.path_to_db)
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
    
    def move_to_fridge(self, product_name: str, quantity: int):
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
            
            if row is None:
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
    
    def get_expiring_products(self) -> tuple[list[any], list[any]]:
        with self.cursor() as cursor:
            today = datetime.now()
            cursor.execute("""
                SELECT id, product_name, quantity, expiration_date FROM fridge WHERE expiration_date <= ?
            """, (today.strftime("%Y-%m-%d"),))
            products = cursor.fetchall()

            if not products:
                return False

            expired_products = []
            expire_today = []
            for product in products:
                if product[3] < today.strftime("%Y-%m-%d"):
                    expired_products.append((product[0], product[1], product[2]))
                elif product[3] == today.strftime("%Y-%m-%d"):
                    expire_today.append((product[0], product[1], product[2]))
            return expired_products, expire_today

    def clear_expired_product(self,id, name: str, quantity: int, reason: str | None):
        with self.cursor() as cursor:
            if quantity <= 0:
                yield ValueError
            cursor.execute("""
                SELECT quantity FROM fridge WHERE id = ?
            """, (id,))
            row = cursor.fetchone()
            if row is None:
                return False
            fridge_quantity = row[0]
            if fridge_quantity - quantity < 0:
                return False
            elif fridge_quantity - quantity > 0:
                cursor.execute("""
                    UPDATE fridge SET quantity = ? WHERE id = ?
                """, (fridge_quantity - quantity, id))
                return f"Списана партия {name} - {quantity} Шт. Осталось {fridge_quantity - quantity} Шт. Причина {reason}"
            else: 
                cursor.execute("""
                    DELETE FROM fridge WHERE id = ?
                """, (id,))
                return f"Партия {name} - {quantity} Шт. списана полностью по причине {reason}"
            

    def new_delivery(self, product_name: str, quantity: int):
        with self.cursor() as cursor:
            if quantity < 0:
                return ValueError

            cursor.execute("""
                SELECT quantity FROM freezer WHERE product_name = ?
            """, (product_name,))

            row = cursor.fetchone()
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

    def fridge_batches_list(self):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT id, product_name, quantity, date_added, expiration_date
                FROM fridge
                ORDER BY expiration_date ASC
            """)
            products = cursor.fetchall()
            return products

    def freezer_products_list(self):
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT product_name, quantity FROM freezer
            """)
            products = cursor.fetchall()
            return products
    

DB = Database(path_to_db="data/database.db")


    
