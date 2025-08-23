# database.py
from supabase import create_client, Client
import os
import datetime
import random
import json

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- CONEXIÓN A LA BASE DE DATOS ---
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
            supabase.from_('users').insert({'user_id': str(user_id), 'lbucks': 0}).execute()
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

# --- FUNCIONES PARA LA TABLA 'invites' ---
def check_and_update_invite_reward(invite_code, inviter_id):
    try:
        response = supabase.from_('invites').select('*').eq('invite_code', invite_code).execute()
        if not response.data:
            supabase.from_('invites').insert({'invite_code': invite_code, 'inviter_id': str(inviter_id)}).execute()
            return

        invite_data = response.data[0]
        if not invite_data['reward_given']:
            update_lbucks(inviter_id, 10) # Recompensa por invitación
            supabase.from_('invites').update({'reward_given': True}).eq('invite_code', invite_code).execute()
            print(f"Recompensa de invitación dada a {inviter_id}")

    except Exception as e:
        print(f"[DB ERROR] Error en check_and_update_invite_reward: {e}")
        
def get_invite_count(inviter_id):
    try:
        response = supabase.from_('invites').select('inviter_id').eq('inviter_id', str(inviter_id)).execute()
        return len(response.data)
    except Exception as e:
        print(f"[DB ERROR] Error en get_invite_count: {e}")
        return 0

# --- FUNCIONES PARA LA TABLA 'missions' ---
def get_daily_missions(user_id):
    try:
        today = datetime.date.today().isoformat()
        response = supabase.from_('user_missions').select('id, progress, is_completed, mission_id').eq('user_id', str(user_id)).eq('assigned_date', today).execute()
        
        if response.data:
            user_missions_data = []
            for m in response.data:
                mission_details = supabase.from_('missions').select('*').eq('mission_id', m['mission_id']).execute().data[0]
                user_missions_data.append({**m, **mission_details})
            return user_missions_data
        else:
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
            
            return get_daily_missions(user_id)
            
    except Exception as e:
        print(f"[DB ERROR] Error en get_daily_missions: {e}")
        return []

# Reemplaza esta función completa en database.py
def update_mission_progress(user_id, mission_type, progress_increase=1, command_name=None):
    try:
        today = datetime.date.today().isoformat()
        response = supabase.from_('user_missions').select('id, progress, mission_id, is_completed').eq('user_id', str(user_id)).eq('assigned_date', today).eq('is_completed', False).execute()
        
        for user_mission in response.data:
            mission_details = supabase.from_('missions').select('*').eq('mission_id', user_mission['mission_id']).execute().data[0]
            
            if mission_details['mission_type'] == mission_type:
                # --- LÓGICA MEJORADA ---
                # 1. Obtenemos el comando específico que la misión requiere (si lo tiene)
                required_command = mission_details.get('trigger_value')
                
                # 2. Si la misión requiere un comando específico, y no es el que se usó, la ignoramos.
                if required_command and required_command != command_name:
                    continue # Pasa a la siguiente misión del usuario

                # --- FIN DE LA LÓGICA MEJORADA ---

                new_progress = user_mission['progress'] + progress_increase
                is_completed = new_progress >= mission_details['target_value']
                
                supabase.from_('user_missions').update({
                    'progress': new_progress,
                    'is_completed': is_completed
                }).eq('id', user_mission['id']).execute()
                
                if is_completed:
                    update_lbucks(user_id, mission_details['reward'])
                    print(f"Misión '{mission_details['description']}' completada por {user_id}. Recompensa: {mission_details['reward']} LBucks.")
                
    except Exception as e:
        print(f"[DB ERROR] Error en update_mission_progress: {e}")

# --- FUNCIONES PARA LA TABLA 'shop' ---
# En database.py
def get_shop_items():
    """Obtiene todos los datos de los ítems de la tienda, incluyendo descripción y emoji."""
    try:
        # Asegúrate de que tu tabla 'shop' tenga las columnas 'description' y 'emoji'
        response = supabase.from_('shop').select('item_id, price, stock, description, emoji').order('price').execute()
        # Devuelve una lista de diccionarios, que es lo que el nuevo código espera
        return response.data
    except Exception as e:
        print(f"[DB ERROR] Error en get_shop_items: {e}")
        # Es crucial devolver una lista vacía en caso de error
        return []

# En database.py, reemplaza esta función

def get_item(item_id):
    """Obtiene los datos de un ítem específico como un diccionario."""
    try:
        # Hacemos que también pida la descripción y el emoji por si lo necesitas en el futuro
        response = supabase.from_('shop').select('item_id, price, stock, description, emoji').eq('item_id', item_id).single().execute()
        # Devuelve el diccionario directamente
        return response.data if response.data else None
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

# --- FUNCIONES PARA EL LEADERBOARD ---

def get_lbucks_leaderboard(limit=10):
    """Obtiene los usuarios con más LBucks desde la tabla 'users'."""
    try:
        response = supabase.from_('users').select('user_id, lbucks').order('lbucks', desc=True).limit(limit).execute()
        return [(user['user_id'], user['lbucks']) for user in response.data]
    except Exception as e:
        print(f"[DB ERROR] Error en get_lbucks_leaderboard: {e}")
        return []

# --- FUNCIONES PARA LA AVENTURA ESPACIAL ---

def get_player_profile(user_id):
    """Obtiene el perfil de aventura de un jugador desde 'adventure_players'."""
    try:
        response = supabase.from_('adventure_players').select('*').eq('user_id', str(user_id)).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"[DB ERROR] Error en get_player_profile: {e}")
        return None

def create_player_profile(user_id):
    """Crea un nuevo perfil de aventura para un jugador."""
    try:
        supabase.from_('adventure_players').insert({'user_id': str(user_id)}).execute()
        print(f"Perfil de aventura creado para el usuario {user_id}")
    except Exception as e:
        print(f"[DB ERROR] Error en create_player_profile: {e}")

def update_player_profile(user_id, updates: dict):
    """Actualiza campos específicos del perfil de un jugador.
    Ejemplo de updates: {'ship_level': 2, 'power_level': 15}
    """
    try:
        supabase.from_('adventure_players').update(updates).eq('user_id', str(user_id)).execute()
    except Exception as e:
        print(f"[DB ERROR] Error en update_player_profile: {e}")

def get_planet_by_id(planet_id):
    """Obtiene la información de un planeta por su ID."""
    try:
        response = supabase.from_('adventure_planets').select('*').eq('planet_id', planet_id).single().execute()
        return response.data
    except Exception as e:
        print(f"[DB ERROR] Error en get_planet_by_id: {e}")
        return None

def get_explorable_planets(conquered_planet_names: list):
    """Obtiene planetas que el usuario NO ha conquistado."""
    try:
        query = supabase.from_('adventure_planets').select('*')

        # --- LA LÍNEA CORREGIDA ESTÁ AQUÍ ---
        # Si la lista de planetas conquistados no está vacía, los filtramos.
        if conquered_planet_names:
            # La sintaxis correcta para "not in" es .not_.in_()
            query = query.not_.in_('name', conquered_planet_names)
        # --- FIN DE LA CORRECCIÓN ---

        response = query.execute()

        # El resto del código para elegir 3 al azar sigue igual
        available_planets = response.data
        if len(available_planets) <= 3:
            return available_planets
        return random.sample(available_planets, k=3)

    except Exception as e:
        print(f"[DB ERROR] Error en get_explorable_planets: {e}")
        return []

def summarize_inventory(user_id):
    """Cuenta los materiales en el inventario de un jugador y los devuelve en un diccionario."""
    try:
        player = get_player_profile(user_id)
        if not player or not player['inventory']:
            return {}
        
        summary = {}
        for item in player['inventory']:
            name = item.get('name')
            if name:
                summary[name] = summary.get(name, 0) + 1
        return summary
    except Exception as e:
        print(f"[DB ERROR] Error en summarize_inventory: {e}")
        return {}


def remove_materials_from_inventory(user_id, materials_to_remove: dict):
    """Elimina una cantidad específica de materiales del inventario de un jugador."""
    try:
        player = get_player_profile(user_id)
        if not player:
            return

        current_inventory = player['inventory']
        
        # Copiamos el diccionario para poder iterar y eliminar de forma segura
        temp_materials_to_remove = materials_to_remove.copy()

        new_inventory = []
        # Iteramos el inventario en orden inverso para poder eliminar sin afectar los índices
        for item in reversed(current_inventory):
            item_name = item.get('name')
            if item_name in temp_materials_to_remove and temp_materials_to_remove[item_name] > 0:
                # Si encontramos un material que necesitamos quitar, lo "gastamos" y no lo añadimos al nuevo inventario
                temp_materials_to_remove[item_name] -= 1
            else:
                # Si no es un material a gastar, lo conservamos
                new_inventory.append(item)
        
        # Volvemos a invertir la lista para que mantenga su orden original
        new_inventory.reverse()

        # Actualizamos la base de datos con el nuevo inventario
        update_player_profile(user_id, {'inventory': new_inventory})

    except Exception as e:
        print(f"[DB ERROR] Error en remove_materials_from_inventory: {e}")
