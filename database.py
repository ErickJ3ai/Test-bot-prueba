import sqlite3
import datetime
import random

DB_NAME = 'evento_robux.db'

def init_db():
    """Inicializa la base de datos y crea todas las tablas si no existen."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        lbucks INTEGER DEFAULT 0,
        last_daily TEXT
    )''')

    # Tabla para el stock y precios de la tienda
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shop (
        item_id TEXT PRIMARY KEY,
        price INTEGER DEFAULT 100,
        stock INTEGER DEFAULT 10
    )''')
    
    # Tabla para registrar los canjeos pendientes
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS redemptions (
        redemption_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_id TEXT,
        message_id INTEGER,
        status TEXT DEFAULT 'pending' -- pending, completed, cancelled_by_admin
    )''')
    
    # --- Tablas para el sistema de Misiones ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS missions (
        mission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_type TEXT UNIQUE, -- 'send_messages', 'invite_users'
        description TEXT,
        target_count INTEGER,
        reward INTEGER
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_missions (
        user_id INTEGER,
        mission_id INTEGER,
        current_progress INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0, -- 0 for false, 1 for true
        PRIMARY KEY (user_id, mission_id),
        FOREIGN KEY(user_id) REFERENCES users(user_id),
        FOREIGN KEY(mission_id) REFERENCES missions(mission_id)
    )''')

    # --- Inserción de datos iniciales ---
    # Inserta los items de la tienda si no existen
    shop_items = ['5_robux', '10_robux', '25_robux', '30_robux', '45_robux', 
                  '55_robux', '60_robux', '75_robux', '80_robux', '100_robux']
    for item in shop_items:
        cursor.execute("INSERT OR IGNORE INTO shop (item_id, price, stock) VALUES (?, 50, 20)", (item,))

    # Inserta misiones base si no existen
    base_missions = [
        ('send_messages', 'Envía 50 mensajes en el servidor.', 50, 25),
        ('invite_users', 'Invita a 1 nuevo miembro al servidor.', 1, 50)
        # Puedes añadir más tipos de misiones aquí
    ]
    cursor.executemany("INSERT OR IGNORE INTO missions (mission_type, description, target_count, reward) VALUES (?, ?, ?, ?)", base_missions)

    conn.commit()
    conn.close()

# --- Funciones de Usuario ---
def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_lbucks(user_id, amount):
    get_user(user_id) # Asegura que el usuario exista
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET lbucks = lbucks + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] # lbucks

def update_daily_claim(user_id):
    now = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()

# --- Funciones de la Tienda ---
def get_shop_items():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id, price, stock FROM shop ORDER BY price")
    items = cursor.fetchall()
    conn.close()
    return items

def get_item(item_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id, price, stock FROM shop WHERE item_id=?", (item_id,))
    item = cursor.fetchone()
    conn.close()
    return item

def update_stock(item_id, amount_change):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE shop SET stock = stock + ? WHERE item_id = ?", (amount_change, item_id))
    conn.commit()
    conn.close()
    
def set_price(item_id, new_price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE shop SET price = ? WHERE item_id = ?", (new_price, item_id))
    conn.commit()
    conn.close()

def set_shop_stock(item_id, quantity):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE shop SET stock = ? WHERE item_id = ?", (quantity, item_id))
    conn.commit()
    conn.close()

# --- Funciones de Canjeo ---
def create_redemption(user_id, item_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO redemptions (user_id, item_id, message_id) VALUES (?, ?, ?)", 
                   (user_id, item_id, message_id))
    conn.commit()
    conn.close()

def get_redemption_by_message(message_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM redemptions WHERE message_id = ?", (message_id,))
    redemption = cursor.fetchone()
    conn.close()
    return redemption

def update_redemption_status(redemption_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE redemptions SET status = ? WHERE redemption_id = ?", (status, redemption_id))
    conn.commit()
    conn.close()
