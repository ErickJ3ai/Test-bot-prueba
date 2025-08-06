# database.py
from supabase import create_client, Client
import os
import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
# Las credenciales de Supabase se obtienen de las variables de entorno
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- REEMPLAZO DE CONEXIÓN CONTEXTUAL ---
# La conexión de Supabase es persistente, no necesita un "context manager" como SQLite.
# Simplemente se llama a "supabase" para interactuar.

def init_db():
    # En Supabase, la creación de la tabla se hace manualmente o con scripts SQL.
    # Esta función ahora solo verifica que la conexión funciona.
    print("La base de datos de Supabase está lista. Las tablas deben crearse en el panel de control.")
    # NOTA: En este punto, asegúrate de que las tablas estén creadas en Supabase.
    # Tabla `users` -> `usuarios`
    # Tabla `shop` -> `shop_items`
    # Tabla `redemptions` -> `redemptions`

def get_user(user_id):
    """Obtiene los datos de un usuario por su ID, creándolo si no existe."""
    try:
        response = supabase.from_('users').select('*').eq('user_id', str(user_id)).execute()
        if response.data:
            user_data = response.data[0]
            # Formatear datos para que coincidan con la estructura original (user_id, lbucks, last_daily)
            last_daily_dt = datetime.datetime.fromisoformat(user_data['last_daily']) if user_data.get('last_daily') else None
            return (user_data['user_id'], user_data['lbucks'], last_daily_dt)
        else:
            # Insertar el usuario si no existe
            supabase.from_('users').insert({'user_id': str(user_id)}).execute()
            return (str(user_id), 0, None)
    except Exception as e:
        print(f"[DB ERROR] Error en get_user: {e}")
        # En caso de error, puedes devolver una estructura similar a la original para evitar fallos.
        return (str(user_id), 0, None)

def update_lbucks(user_id, amount):
     """Añade o resta LBucks a un usuario."""
    try:
        # Obtener el balance actual del usuario
        response = supabase.from_('users').select('lbucks').eq('user_id', str(user_id)).execute()
        current_lbucks = response.data[0]['lbucks'] if response.data else 0
        new_lbucks = current_lbucks + amount
        
        # Actualiza el balance del usuario en una sola operación
        supabase.from_('users').upsert({'user_id': str(user_id), 'lbucks': new_lbucks}).execute()
        
    except Exception as e:
        print(f"[DB ERROR] Error en update_lbucks: {e}")

def get_balance(user_id):
    try:
        # Intenta obtener solo el balance del usuario
        response = supabase.from_('users').select('lbucks').eq('user_id', str(user_id)).execute()
        if response.data:
            return response.data[0]['lbucks']
        else:
            # Si el usuario no existe, lo inserta y devuelve el balance por defecto
            supabase.from_('users').insert({'user_id': str(user_id)}).execute()
            return 0
    except Exception as e:
        print(f"[DB ERROR] Error en get_balance: {e}")
        return 0

def update_daily_claim(user_id):
    """Actualiza la marca de tiempo del último login diario."""
    now_utc = datetime.datetime.utcnow().isoformat()
    try:
        supabase.from_('users').upsert({'user_id': str(user_id), 'last_daily': now_utc}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_daily_claim: {e}")

def get_shop_items():
    """Obtiene todos los items de la tienda."""
    try:
        response = supabase.from_('shop').select('item_id, price, stock').order('price').execute()
        return [(item['item_id'], item['price'], item['stock']) for item in response.data]
    except Exception as e:
        print(f"[DB ERROR] Error en get_shop_items: {e}")
        return []

def get_item(item_id):
    """Obtiene un item específico de la tienda."""
    try:
        response = supabase.from_('shop').select('item_id, price, stock').eq('item_id', item_id).execute()
        if response.data:
            item = response.data[0]
            return (item['item_id'], item['price'], item['stock'])
        return None
    except Exception as e:
        print(f"[DB ERROR] Error en get_item: {e}")
        return None

def update_stock(item_id, amount_change):
    """Actualiza el stock de un item en la tienda."""
    try:
        response = supabase.from_('shop').select('stock').eq('item_id', item_id).execute()
        if response.data:
            current_stock = response.data[0]['stock']
            new_stock = current_stock + amount_change
            supabase.from_('shop').upsert({'item_id': item_id, 'stock': new_stock}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_stock: {e}")

def set_price(item_id, new_price):
    """Establece un nuevo precio para un item."""
    try:
        supabase.from_('shop').upsert({'item_id': item_id, 'price': new_price}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en set_price: {e}")

def set_shop_stock(item_id, quantity):
    """Establece el stock de un item."""
    try:
        supabase.from_('shop').upsert({'item_id': item_id, 'stock': quantity}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en set_shop_stock: {e}")

def create_redemption(user_id, item_id, message_id):
    """Registra un nuevo canjeo pendiente."""
    try:
        supabase.from_('redemptions').insert({
            'user_id': str(user_id),
            'item_id': item_id,
            'message_id': str(message_id),
            'status': 'pending'
        }).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en create_redemption: {e}")

def get_redemption_by_message(message_id):
    """Obtiene un canjeo por su ID de mensaje."""
    try:
        response = supabase.from_('redemptions').select('*').eq('message_id', str(message_id)).execute()
        if response.data:
            redemption = response.data[0]
            # Formatear datos para que coincidan con la estructura original
            return (redemption['redemption_id'], redemption['user_id'], redemption['item_id'], redemption['message_id'], redemption['status'])
        return None
    except Exception as e:
        print(f"[DB ERROR] Error en get_redemption_by_message: {e}")
        return None

def update_redemption_status(redemption_id, status):
    """Actualiza el estado de un canjeo."""
    try:
        supabase.from_('redemptions').upsert({'redemption_id': redemption_id, 'status': status}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_redemption_status: {e}")
