# database.py
from supabase import create_client, Client
import os
import datetime
import random

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- REEMPLAZO DE CONEXIÓN CONTEXTUAL ---
def init_db():
    print("La base de datos de Supabase está lista. Las tablas deben crearse en el panel de control.")

# --- FUNCIONES PARA LA TABLA 'users' ---
def get_user(user_id):
    try:
        response = supabase.from_('users').select('*').eq('user_id', str(user_id)).execute()
        if response.data:
            user_data = response.data[0]
            last_daily_dt = datetime.datetime.fromisoformat(user_data['last_daily']).replace(tzinfo=datetime.timezone.utc) if user_data.get('last_daily') else None
            return (user_data['user_id'], user_data['lbucks'], last_daily_dt)
        else:
            supabase.from_('users').insert({'user_id': str(user_id)}).execute()
            return (str(user_id), 0, None)
    except Exception as e:
        print(f"[DB ERROR] Error en get_user: {e}")
        return (str(user_id), 0, None)

def update_lbucks(user_id, amount):
    try:
        response = supabase.from_('users').select('lbucks').eq('user_id', str(user_id)).execute()
        current_lbucks = response.data[0]['lbucks'] if response.data else 0
        new_lbucks = current_lbucks + amount
        supabase.from_('users').upsert({'user_id': str(user_id), 'lbucks': new_lbucks}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_lbucks: {e}")

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 0

def update_daily_claim(user_id):
    now_utc = datetime.datetime.utcnow().isoformat()
    try:
        supabase.from_('users').upsert({'user_id': str(user_id), 'last_daily': now_utc}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_daily_claim: {e}")

# --- FUNCIONES PARA LA TABLA 'missions' ---
def get_daily_missions(user_id):
    try:
        # 1. Verificar si ya tiene misiones asignadas para hoy
        today = datetime.date.today().isoformat()
        response = supabase.from_('user_missions').select('id, progress, is_completed, mission_id').eq('user_id', str(user_id)).eq('assigned_date', today).execute()
        
        if response.data:
            # 2. Si ya tiene misiones, devolverlas
            user_missions_data = []
            for m in response.data:
                mission_details = supabase.from_('missions').select('*').eq('mission_id', m['mission_id']).execute().data[0]
                user_missions_data.append({**m, **mission_details})
            return user_missions_data
        else:
            # 3. Si no, asignar 4 misiones aleatorias
            supabase.from_('user_missions').delete().eq('user_id', str(user_id)).execute()
            all_missions = supabase.from_('missions').select('*').execute().data
            if not all_missions:
                return []
            
            random_missions = random.sample(all_missions, k=4)
            
            missions_to_insert = []
            for m in random_missions:
                missions_to_insert.append({
                    'user_id': str(user_id),
                    'mission_id': m['mission_id'],
                    'progress': 0,
                    'is_completed': False,
                    'assigned_date': today
                })
            
            supabase.from_('user_missions').insert(missions_to_insert).execute()
            
            # Devolver las misiones recién asignadas
            return get_daily_missions(user_id)
            
    except Exception as e:
        print(f"[DB ERROR] Error en get_daily_missions: {e}")
        return []

def update_mission_progress(user_id, mission_type, progress_increase=1):
    try:
        today = datetime.date.today().isoformat()
        response = supabase.from_('user_missions').select('id, progress, mission_id, is_completed').eq('user_id', str(user_id)).eq('assigned_date', today).eq('is_completed', False).execute()
        
        for user_mission in response.data:
            mission_details = supabase.from_('missions').select('*').eq('mission_id', user_mission['mission_id']).execute().data[0]
            
            if mission_details['mission_type'] == mission_type:
                new_progress = user_mission['progress'] + progress_increase
                
                # Marcar como completada si el progreso alcanza el objetivo
                is_completed = new_progress >= mission_details['target_value']
                
                supabase.from_('user_missions').upsert({
                    'id': user_mission['id'],
                    'progress': new_progress,
                    'is_completed': is_completed
                }).execute()
                
                # Si se completó, dar la recompensa
                if is_completed:
                    update_lbucks(user_id, mission_details['reward'])
                    print(f"Misión completada por {user_id}. Recompensa: {mission_details['reward']} LBucks.")
                
    except Exception as e:
        print(f"[DB ERROR] Error en update_mission_progress: {e}")


# --- FUNCIONES PARA LA TABLA 'shop' ---
def get_shop_items():
    try:
        response = supabase.from_('shop').select('item_id, price, stock').order('price').execute()
        return [(item['item_id'], item['price'], item['stock']) for item in response.data]
    except Exception as e:
        print(f"[DB ERROR] Error en get_shop_items: {e}")
        return []

def get_item(item_id):
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
    try:
        response = supabase.from_('shop').select('stock').eq('item_id', item_id).execute()
        if response.data:
            current_stock = response.data[0]['stock']
            new_stock = current_stock + amount_change
            supabase.from_('shop').upsert({'item_id': item_id, 'stock': new_stock}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_stock: {e}")

def set_price(item_id, new_price):
    try:
        supabase.from_('shop').upsert({'item_id': item_id, 'price': new_price}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en set_price: {e}")

def set_shop_stock(item_id, quantity):
    try:
        supabase.from_('shop').upsert({'item_id': item_id, 'stock': quantity}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en set_shop_stock: {e}")

# --- FUNCIONES PARA LA TABLA 'redemptions' ---
def create_redemption(user_id, item_id, message_id):
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
    try:
        response = supabase.from_('redemptions').select('*').eq('message_id', str(message_id)).execute()
        if response.data:
            redemption = response.data[0]
            return (redemption['redemption_id'], redemption['user_id'], redemption['item_id'], redemption['message_id'], redemption['status'])
        return None
    except Exception as e:
        print(f"[DB ERROR] Error en get_redemption_by_message: {e}")
        return None

def update_redemption_status(redemption_id, status):
    try:
        supabase.from_('redemptions').upsert({'redemption_id': redemption_id, 'status': status}).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_redemption_status: {e}")
