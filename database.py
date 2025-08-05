import sqlite3
import datetime
from contextlib import contextmanager

DB_NAME = 'evento_robux.db'

@contextmanager
def get_connection():
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        yield conn
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"[DB ERROR] {e}")
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lbucks INTEGER DEFAULT 0,
            last_daily TEXT
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop (
            item_id TEXT PRIMARY KEY,
            price INTEGER,
            stock INTEGER
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS redemptions (
            redemption_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id TEXT,
            message_id INTEGER,
            status TEXT DEFAULT 'pending'
        )''')

        shop_items = [
            ('5_robux', 50, 20), ('10_robux', 100, 20), ('25_robux', 250, 15),
            ('30_robux', 300, 15), ('45_robux', 450, 10), ('55_robux', 550, 10),
            ('60_robux', 600, 5), ('75_robux', 750, 5), ('80_robux', 800, 5),
            ('100_robux', 1000, 3)
        ]
        cursor.executemany("INSERT OR IGNORE INTO shop (item_id, price, stock) VALUES (?, ?, ?)", shop_items)

def get_user(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def update_lbucks(user_id, amount):
    get_user(user_id)  # Ensure user exists
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET lbucks = lbucks + ? WHERE user_id = ?", (amount, user_id))

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 0

def update_daily_claim(user_id):
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user_id))

def get_shop_items():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, price, stock FROM shop ORDER BY price")
        return cursor.fetchall()

def get_item(item_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, price, stock FROM shop WHERE item_id=?", (item_id,))
        return cursor.fetchone()

def update_stock(item_id, amount_change):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE shop SET stock = stock + ? WHERE item_id = ?", (amount_change, item_id))

def set_price(item_id, new_price):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE shop SET price = ? WHERE item_id = ?", (new_price, item_id))

def set_shop_stock(item_id, quantity):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE shop SET stock = ? WHERE item_id = ?", (quantity, item_id))

def create_redemption(user_id, item_id, message_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO redemptions (user_id, item_id, message_id) VALUES (?, ?, ?)", 
                       (user_id, item_id, message_id))

def get_redemption_by_message(message_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM redemptions WHERE message_id = ?", (message_id,))
        return cursor.fetchone()

def update_redemption_status(redemption_id, status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE redemptions SET status = ? WHERE redemption_id = ?", (status, redemption_id))
