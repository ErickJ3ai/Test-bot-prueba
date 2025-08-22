# -*- coding: utf-8 -*-
import discord
from discord import Object
from discord.ext import commands
from discord.ui import Button, View
import os
from dotenv import load_dotenv
import datetime
from flask import Flask
from threading import Thread
from waitress import serve
import database as db
from config import GUILD_ID, ADMIN_ROLE_NAME, REDEMPTION_LOG_CHANNEL_ID
import asyncio
import random
import aiohttp
from unidecode import unidecode

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True
bot = discord.Bot(intents=intents)

# --- 2. JUEGOS, LISTAS Y GESTIÓN DE ESTADO ---
number_games = {}
word_games = {}
voice_join_times = {}
# --- DATOS DEL JUEGO DE AVENTURA ---
PLANET_NAMES = [
    "Xylar", "Krypton Prime", "Nebulon-9", "Cygnus X-1", "Aethelgard",
    "Veridian-IV", "Ryzen-7", "Gliese-581g", "Kepler-186f", "Trappist-1e",
    "Zandor", "Helios Prime", "Orionis", "Sirius-B", "Proxima Centauri-b",
    "Andromeda-IX", "Magellanic Cloud-3", "Taurus-V", "Lyra-Delta", "Draco-II",
    "Aquila-Rift", "Pegasus-Omega", "Ursa-Minor-Beta", "Hydra-Core", "Volantis",
    "Qo'noS", "Cardassia-Prime", "Vulcan", "Ryloth", "Tatooine-Secundus"
]
LOOT_TABLE = {
    'Fácil': [
        {'name': 'Fragmento de Titanio', 'value': 5},
        {'name': 'Cableado Básico', 'value': 3},
        {'name': 'Chatarra Espacial', 'value': 1}
    ],
    'Intermedio': [
        {'name': 'Placa de Acero Reforzado', 'value': 15},
        {'name': 'Cristal de Kyber (Pequeño)', 'value': 20},
        {'name': 'Procesador de Navegación', 'value': 18}
    ],
    'Difícil': [
        {'name': 'Núcleo de Energía de Singularidad', 'value': 50},
        {'name': 'Aleación de Neutronio', 'value': 60},
        {'name': 'Mapa Estelar Antiguo', 'value': 45}
    ]
}
SHOP_ITEMS = {
    'blaster_basico': {'name': 'Bláster Básico MK2', 'price': 50, 'power_increase': 5, 'type': 'ship'},
    'escudo_inicial': {'name': 'Escudo Deflector Básico', 'price': 75, 'power_increase': 8, 'type': 'ship'},
    'mina_automatica': {'name': 'Mina Automática de Asteroides', 'price': 100, 'power_increase': 12, 'type': 'station'},
    'torreta_defensiva': {'name': 'Torreta de Defensa Orbital', 'price': 120, 'power_increase': 15, 'type': 'station'}
}
ASCII_ART = {
    'intro': r"""
     _.-._
   | | | |_
   | | | | |
   | | | | |
 _ |  '-._ |
 \`'--'   ' ._
  '.____.'__`'-,
   `--..____'.   '.
   ​'.--.     '..' .   |
'. '-..____.'.    ' | '.       '.   .' '.        ' '._ '--.._
'.               '--.._ '-.      /            '--.._
'---'                    '---.._
`'---.._
""",
    'station': r"""
    """
}

# Puedes agregar todas las palabras que quieras a esta lista
PALABRAS_LOCALES = [
    "computadora", "biblioteca", "desarrollo", "guitarra", "universo",
    "aventura", "botella", "estrella", "planeta", "galaxia", "elefante",
    "jirafa", "cocodrilo", "murcielago", "mariposa", "teclado", "montaña",
    "programacion", "inteligencia", "artificial", "videojuego", "discord", 
    "pensamiento", "encuadernado", "psiquiatra", "psicologia", "carpinteria", 
    "humanidad", "emprendimiento", "terrateniente", "nucleares", "agnostico", 
    "pronostico", "aleatorio", "termodinamica", "prioridad", "sistematico", 
    "veracidad", "parlamento", "oratoria", "permutaciones", "formalidad", 
    "otorrinolaringologo", "esternocleidomastoideo", "Ovoviparo", "anacronismo", 
    "calamidad", "cardiologo", "Indomito", "frecuente", "Principalmente", "Contrarrevolucionario", 
    "Cientificismo", "Paralelepipedo", "Transustanciacion", "estampida", "primogenitos", 
    "judicatura", "estacionario", "cualificacion", "historiagrama", "gubernamental", 
    "adjudicarse", "Muchedumbre", "hidraulico", "criminologia", "revolucion", "tirania", 
    "embebido", "embotellamiento", "electromagnetismo", "cuantitativo", "cualitativo", 
    "primavera", "empobrecer", "egocentrismo", "abstraccion", "abstinencia", "equivalencia",
    "ojimetro", "hispanicos", "lexicografica", "estrategico", "pasarela", "caligrafico", "sanscrito",
    "transcripcion", "heterogramas", "heraldica", "Enciclopedico", "interjeccion", "Delimitacion", 
    "estructurarse", "locuciones", "diferenciacion", "exhaustivo", "refrendaban", "acepciones", 
    "hispanohablante", "nutrida", "caricatura", "sismologia", "arandanos", "luminiscencia", 
    "espejismo", "translucidos", "transformarse", "mutuo", "dualidad", "existencialismo", 
    "cabellera", "extinguir", "frontera", "adelgazar", "dramatizar", "ñandu", "inmobiliaria", 
    "monotono", "reeducacion", "titulacion", "advertencia", "magdalena", "magnate", "bobina",
    "curaciones", "mercurio", "precipitarse", "precipicio",
    "rabia", "somatico", "movilizacion", "embaucar", "momentaneo"
]

HANGMAN_PICS = [
    '```\n +---+\n |   |\n     |\n     |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n     |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n |   |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|   |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n/    |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n/ \\  |\n     |\n=========\n```'
]

async def get_random_word_local():
    palabra = random.choice(PALABRAS_LOCALES)
    return unidecode(palabra.lower())

def create_hangman_embed(game_state, game_over_status=None):
    word = game_state['word']
    hint = " ".join([c if c in game_state['guessed_letters'] else "＿" for c in word])
    embed = discord.Embed(color=discord.Color.blue())
    
    if game_over_status == "win":
        embed.title = "🎉 ¡Felicidades, has ganado! 🎉"
        embed.description = f"La palabra era: **{word.capitalize()}**"
        embed.color = discord.Color.green()
    elif game_over_status == "loss":
        embed.title = "☠️ ¡Oh no, has perdido! ☠️"
        embed.description = f"La palabra era: **{word.capitalize()}**"
        embed.color = discord.Color.red()
    else:
        embed.title = "🤔 Juego del Ahorcado 🤔"
        embed.description = "Adivina la palabra enviando una letra en este canal."
        
    embed.add_field(name="Palabra", value=f"`{hint}`", inline=False)
    mistakes = game_state['mistakes']
    embed.add_field(name="Progreso", value=HANGMAN_PICS[mistakes], inline=True)
    wrong_letters = ", ".join(sorted(list(game_state['wrong_guesses']))) or "Ninguna"
    embed.add_field(name="Letras Incorrectas", value=wrong_letters, inline=True)
    return embed

async def check_word_game_timeout():
    while True:
        await asyncio.sleep(60)
        to_delete = []
        now = datetime.datetime.now()
        for channel_id, game in word_games.items():
            if now - game['start_time'] > datetime.timedelta(minutes=7):
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"¡Se acabó el tiempo para el juego de adivinar palabras! La palabra era '{game['word']}'.")
                to_delete.append(channel_id)
        for channel_id in to_delete:
            if channel_id in word_games:
                del word_games[channel_id]

# --- 3. VISTAS DE BOTONES (UI) ---
class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        self.amount_input = discord.ui.InputText(
            label="Cantidad de LBucks",
            placeholder="Introduce la cantidad a donar",
            min_length=1,
            max_length=10,
            style=discord.InputTextStyle.short)
        self.recipient_input = discord.ui.InputText(
            label="Destinatario (ID o nombre de usuario)",
            placeholder="Introduce el ID o nombre de usuario de la persona",
            min_length=1,
            max_length=32,
            style=discord.InputTextStyle.short)
        self.add_item(self.amount_input)
        self.add_item(self.recipient_input)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            amount = int(self.amount_input.value)
            recipient_str = self.recipient_input.value
            if recipient_str.isdigit():
                recipient = await bot.fetch_user(int(recipient_str))
            else:
                recipient = discord.utils.get(interaction.guild.members,
                                              name=recipient_str)
            if recipient is None:
                await interaction.followup.send(
                    "No se pudo encontrar al destinatario.", ephemeral=True)
                return
            if amount <= 0:
                await interaction.followup.send(
                    "La cantidad a donar debe ser un número positivo.",
                    ephemeral=True)
                return
            if interaction.user.id == recipient.id:
                await interaction.followup.send(
                    "No puedes donarte LBucks a ti mismo.", ephemeral=True)
                return
            doner_balance = await asyncio.to_thread(db.get_balance,
                                                    interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send(
                    "No tienes suficientes LBucks para donar.", ephemeral=True)
                return
            await asyncio.to_thread(db.update_lbucks, interaction.user.id,
                                    -amount)
            await asyncio.to_thread(db.update_lbucks, recipient.id, amount)
            await interaction.followup.send(
                f"Has donado **{amount} LBucks** a **{recipient.name}**. ¡Gracias por tu generosidad! 🎉",
                ephemeral=True)
        except ValueError:
            await interaction.followup.send(
                "La cantidad debe ser un número válido.", ephemeral=True)
        except Exception as e:
            print(f"Error en el modal de donación: {e}")
            await interaction.followup.send(
                "Ocurrió un error al procesar tu donación. Intenta de nuevo más tarde.",
                ephemeral=True)

class RedeemMenuView(View):
    def __init__(self, items):
        super().__init__(timeout=300)
        self.items = items
        for i, (item_id, price, stock) in enumerate(self.items):
            robux_amount = item_id.split('_')[0]
            label = f"{robux_amount} ⏣ ({price} LBucks)"
            button = Button(label=label,
                            custom_id=f"redeem_{item_id}",
                            style=discord.ButtonStyle.blurple,
                            disabled=(stock <= 0))
            button.callback = self.handle_redeem_click
            self.add_item(button)

    async def handle_redeem_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        custom_id = interaction.data['custom_id']
        item_id = custom_id.replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item:
            return await interaction.followup.send("Este item ya no existe.",
                                                   ephemeral=True)
        view = ConfirmCancelView(user_id=interaction.user.id,
                                 item_id=item_id,
                                 price=item[1])
        await interaction.followup.send(
            f"¿Confirmas el canje de **{item[0].split('_')[0]} Robux** "
            f"por **{item[1]} LBucks**?",
            view=view,
            ephemeral=True)

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar Canjeo",
                       style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button,
                             interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        item_data = await asyncio.to_thread(db.get_item, self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send(
                "¡Justo se agotó! Alguien más fue más rápido.")
            return
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.")
            return
        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(
                title="⏳ Nuevo Canjeo Pendiente",
                description=
                f"El usuario **{interaction.user.name}** ({interaction.user.id}) ha canjeado **{robux_amount} Robux**.",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.utcnow())
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed,
                                                 view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id,
                                    self.item_id, log_message.id)
        await interaction.followup.send(
            "¡Canjeo realizado! Un administrador revisará tu solicitud.")
        await interaction.edit_original_response(content="Procesando...",
                                                 view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button,
                            interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="Tu canjeo ha sido cancelado.", view=None)


class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Completar",
                       style=discord.ButtonStyle.success,
                       custom_id="persistent:admin_complete")
    async def complete_button(self, button: Button,
                              interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles,
                                       name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.",
                                                   ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message,
                                             interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(
                content="Este canjeo ya fue procesado.", view=None, embed=None)
        await asyncio.to_thread(db.update_redemption_status, redemption[0],
                                'completed')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(
                f"✅ ¡Tu canjeo de **{item_name}** ha sido completado!")
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "✅ Canjeo Completado"
        edited_embed.color = discord.Color.green()
        edited_embed.add_field(name="Procesado por",
                               value=interaction.user.mention,
                               inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

    @discord.ui.button(label="Rechazar",
                       style=discord.ButtonStyle.danger,
                       custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button,
                            interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles,
                                       name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.",
                                                   ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message,
                                             interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(
                content="Este canjeo ya fue procesado.", view=None, embed=None)
        item = await asyncio.to_thread(db.get_item, redemption[2])
        if item:
            await asyncio.to_thread(db.update_lbucks, redemption[1], item[1])
            await asyncio.to_thread(db.update_stock, redemption[2], 1)
        await asyncio.to_thread(db.update_redemption_status, redemption[0],
                                'cancelled_by_admin')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(
                f"❌ Tu canjeo de **{item_name}** fue cancelado. Tus LBucks han sido devueltos."
            )
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "❌ Canjeo Cancelado por Admin"
        edited_embed.color = discord.Color.dark_grey()
        edited_embed.add_field(name="Cancelado por",
                               value=interaction.user.mention,
                               inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

class UpdateBalanceView(View):
    def __init__(self):
        super().__init__(timeout=None) # <-- Vista Persistente

    @discord.ui.button(label="🔄 Actualizar Saldo",
                       style=discord.ButtonStyle.primary, # <-- Mejor color
                       custom_id="persistent:update_balance") # <-- Custom ID persistente
    async def update_balance_button(self, button: Button,
                                    interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # <-- Defer para evitar errores
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.followup.send(
            f"Tu saldo actualizado es: **{balance} LBucks** 🪙", ephemeral=True)


class UpdateMissionsView(View):
    def __init__(self):
        super().__init__(timeout=None) # <-- Vista Persistente

    @discord.ui.button(label="🔄 Actualizar Misiones",
                       style=discord.ButtonStyle.primary,
                       custom_id="persistent:update_missions")
    async def update_missions_button(self, button: Button,
                                     interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        missions = await asyncio.to_thread(db.get_daily_missions,
                                           interaction.user.id)
        embed = discord.Embed(
            title="📝 Tus Misiones Diarias",
            description="Completa estas misiones para ganar LBucks.",
            color=discord.Color.blue())
        if not missions:
            embed.description = "No hay misiones disponibles en este momento."
        else:
            for m in missions:
                status_emoji = "✅" if m['is_completed'] else "⌛"
                progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
                embed.add_field(
                    name=f"{status_emoji} {m['description']}",
                    value=f"Recompensa: **{m['reward']} LBucks** {progress_text}",
                    inline=False)
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

class PlanetSelectionView(discord.ui.View):
    def __init__(self, planets: list, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        
        for planet in planets:
            button = discord.ui.Button(
                label=f"{planet['name']} ({planet['difficulty']})",
                style=self.get_button_style(planet['difficulty']),
                custom_id=f"planet_{planet['planet_id']}"
            )
            button.callback = self.planet_button_callback
            self.add_item(button)
            
    def get_button_style(self, difficulty: str) -> discord.ButtonStyle:
        if difficulty == 'Fácil': return discord.ButtonStyle.success
        if difficulty == 'Intermedio': return discord.ButtonStyle.primary
        if difficulty == 'Difícil': return discord.ButtonStyle.danger
        return discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("No puedes usar los botones de otro comandante.", ephemeral=True)
            return False
        return True

    async def planet_button_callback(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        player_id = interaction.user.id
        planet_id = int(interaction.data['custom_id'].split('_')[1])
        
        planet = await asyncio.to_thread(db.get_planet_by_id, planet_id)
        player = await asyncio.to_thread(db.get_player_profile, player_id)

        if not planet or not player:
            await interaction.followup.send("Hubo un error al obtener los datos del combate. Inténtalo de nuevo.", ephemeral=True)
            return

        difficulty_multiplier = {'Fácil': 0.5, 'Intermedio': 1.0, 'Difícil': 1.5}
        planet_power = random.randint(5, 20) * difficulty_multiplier.get(planet['difficulty'], 1.0)
        player_power = player['power_level']
        
        chance_to_win = min(0.95, 0.5 + ((player_power - planet_power) / (player_power + 1)))

        if random.random() < chance_to_win:
            reward = planet['reward_lbucks']
            loot = random.choice(LOOT_TABLE.get(planet['difficulty'], []))
            
            await asyncio.to_thread(db.update_lbucks, player_id, reward)
            
            current_inventory = player['inventory']
            current_inventory.append(loot)
            
            conquered_planets = player['conquered_planets']
            conquered_planets.append(planet['name'])
            
            updates = {
                'inventory': current_inventory,
                'conquered_planets': conquered_planets
            }
            await asyncio.to_thread(db.update_player_profile, player_id, updates)
            
            embed = discord.Embed(title=f"✅ ¡Victoria en {planet['name']}!", color=discord.Color.green())
            embed.description = "Has conquistado el planeta y asegurado sus recursos."
            embed.add_field(name="Recompensa Obtenida", value=f"**{reward}** LBucks 🪙")
            embed.add_field(name="Material Recuperado", value=f"**1x {loot['name']}**")
        else:
            embed = discord.Embed(title=f"❌ Derrota en {planet['name']}", color=discord.Color.red())
            embed.description = "Las defensas del planeta eran demasiado fuertes. Tu nave ha sufrido daños, pero logró escapar. Necesitarás más poder para conquistarlo."

        await interaction.followup.send(embed=embed, ephemeral=True)
        
# --- 4. EVENTOS Y LISTENERS ---
invites_cache = {}

@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")
    await bot.sync_commands()
    print("🔄 Comandos slash sincronizados.")
    
    try:
        await asyncio.to_thread(db.init_db)
        print("✔️ Base de datos inicializada.")
    except Exception as e:
        print(f"⚠️ Error al inicializar la base de datos: {e}")

    if not hasattr(bot, "persistent_views_added"):
        bot.add_view(AdminActionView())
        bot.add_view(UpdateBalanceView())
        bot.add_view(UpdateMissionsView())
        bot.persistent_views_added = True
        print("👁️ Vistas persistentes registradas.")

    print("⏳ Caché de invitaciones...")
    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            print(f"Error: Permisos faltantes para leer invitaciones en el servidor {guild.name}")
    
    bot.loop.create_task(check_word_game_timeout())


@bot.event
async def on_member_join(member):
    await asyncio.sleep(5)
    try:
        new_invites = await member.guild.invites()
        old_invites = invites_cache.get(member.guild.id, [])
        used_invite = None
        for new_invite in new_invites:
            for old_invite in old_invites:
                if new_invite.code == old_invite.code and new_invite.uses > old_invite.uses:
                    used_invite = new_invite
                    break
            if used_invite:
                break
        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            await asyncio.to_thread(db.check_and_update_invite_reward, used_invite.code, inviter.id)
    except Exception as e:
        print(f"Error en on_member_join: {e}")
    finally:
        invites_cache[member.guild.id] = await member.guild.invites()


@bot.listen("on_raw_reaction_add")
async def mission_reaction_tracker(payload: discord.RawReactionActionEvent):
    """
    Listener que se activa cuando un usuario añade una reacción a un mensaje.
    """
    if not payload.guild_id:
        return

    user = bot.get_user(payload.user_id)
    if not user or user.bot:
        return

    try:
        channel = await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Evitar progreso por reaccionar a mensajes de bots o a los propios
        if message.author.bot or message.author.id == user.id:
            return
            
        await asyncio.to_thread(
            db.update_mission_progress,
            payload.user_id,
            "reaction_add"
        )
        print(f"Misión de reacción registrada para {user.name}.")

    except (discord.NotFound, discord.Forbidden):
        pass # El mensaje o canal fue borrado o no hay permisos
    except Exception as e:
        print(f"Error en el listener de reacciones: {e}")


@bot.event
async def on_application_command_completion(ctx: discord.ApplicationContext):
    """
    Listener que se activa después de que cualquier comando slash se completa.
    """
    if ctx.author.bot:
        return
    
    # Enviamos el nombre específico del comando a la base de datos
    await asyncio.to_thread(
        db.update_mission_progress, 
        ctx.author.id, 
        "slash_command_use", 
        command_name=ctx.command.name
    )
    print(f"Misión de comando slash '{ctx.command.name}' registrada para {ctx.author.name}.")

# ... (Aquí continúan los demás listeners que ya tienes, como on_message y on_voice_state_update)


@bot.listen("on_message")
async def on_message_handler(message):
    if message.author.bot:
        return

    await asyncio.to_thread(db.update_mission_progress, message.author.id, "message_count")

    channel_id = message.channel.id
    if channel_id in word_games:
        game = word_games[channel_id]
        guess = unidecode(message.content.lower())
        
        try:
            await message.delete()
        except discord.Forbidden:
            pass

        if not (len(guess) == 1 and guess.isalpha()):
            return

        if guess in game['guessed_letters'] or guess in game['wrong_guesses']:
            return

        game_message = await message.channel.fetch_message(game['message_id'])

        if guess in game['word']:
            game['guessed_letters'].add(guess)
            word_complete = all(letter in game['guessed_letters'] for letter in game['word'])
            
            if word_complete:
                reward = 12 # <-- RECOMPENSA ACTUALIZADA
                await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
                win_embed = create_hangman_embed(game, game_over_status="win")
                await game_message.edit(embed=win_embed)
                await message.channel.send(f"¡{message.author.mention} ha adivinado la palabra y gana **{reward} LBucks**!")
                del word_games[channel_id]
            else:
                update_embed = create_hangman_embed(game)
                await game_message.edit(embed=update_embed)
        else:
            game['wrong_guesses'].add(guess)
            game['mistakes'] += 1
            
            if game['mistakes'] >= len(HANGMAN_PICS) - 1:
                loss_embed = create_hangman_embed(game, game_over_status="loss")
                await game_message.edit(embed=loss_embed)
                del word_games[channel_id]
            else:
                update_embed = create_hangman_embed(game)
                await game_message.edit(embed=update_embed)


# Reemplaza tu listener de voz actual con este en bot.py
@bot.listen("on_voice_state_update")
async def mission_voice_tracker(member, before, after):
    if member.bot:
        return

    # Caso 1: Usuario ENTRA a un canal de voz
    if before.channel is None and after.channel is not None:
        # Guardamos la hora exacta en que se unió
        voice_join_times[member.id] = datetime.datetime.now()
        print(f"{member.name} se unió al canal de voz.")

    # Caso 2: Usuario SALE de un canal de voz
    elif before.channel is not None and after.channel is None:
        # Verificamos si habíamos guardado su hora de entrada
        if member.id in voice_join_times:
            join_time = voice_join_times.pop(member.id) # Obtenemos y eliminamos su registro
            duration_seconds = (datetime.datetime.now() - join_time).total_seconds()
            
            # Convertimos la duración a minutos y la redondeamos
            duration_minutes = round(duration_seconds / 60)

            # Solo actualizamos la misión si estuvo al menos 1 minuto para no contar entradas y salidas rápidas
            if duration_minutes > 0:
                print(f"{member.name} salió. Duración: {duration_minutes} minuto(s). Actualizando misión.")
                await asyncio.to_thread(
                    db.update_mission_progress,
                    member.id,
                    "voice_minutes",  # Asegúrate que este 'mission_type' coincida con tu DB
                    progress_increase=duration_minutes
                )


# --- 5. COMANDOS SLASH ---
@bot.slash_command(
    guild_ids=[GUILD_ID], name="ayuda", description="Muestra el menú de comandos."
)
async def ayuda(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(
        title="📚 Guía de Comandos del Bot",
        description="Aquí tienes todos los comandos disponibles.",
        color=discord.Color.blue())
    
    embed.add_field(name="💰 Economía", value="`/saldo`, `/donar`, `/canjear`, `/login_diario`, `/leaderboard`", inline=False)
    embed.add_field(name="🚀 Aventura Espacial", value="`/aventura iniciar`, `/aventura perfil`, `/aventura explorar`", inline=False)
    embed.add_field(name="🕹️ Juegos", value="`/juego palabra` (Ahorcado)\n`/juego numero` (Adivinar Número)\n`/adivinar` (Para el juego de número)", inline=False)
    embed.add_field(name="👥 Social", value="`/invitaciones`", inline=False)
    embed.add_field(name="📋 Misiones", value="`/misiones`", inline=False)
    
    embed.set_footer(text=f"Bot de {ctx.guild.name}")
    await ctx.followup.send(embed=embed, ephemeral=True)

# ... (Aquí van los comandos /login_diario, /canjear, /saldo, /donar, /misiones, /invitaciones que no cambiaron)
@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="login_diario",
    description="Reclama tu recompensa diaria 💷"
)
async def daily_command(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    try:
        user_id = ctx.user.id
        # Tu función get_user ya devuelve un objeto datetime o None en la tercera posición.
        user_data = await asyncio.to_thread(db.get_user, user_id)
        
        # Obtenemos directamente el objeto datetime. No hay que convertir nada.
        last_claim_time = user_data[2]
        
        if last_claim_time is not None:
            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            # Comparamos si han pasado menos de 15 horas
            if current_time - last_claim_time < datetime.timedelta(hours=15):
                time_left = datetime.timedelta(hours=15) - (current_time - last_claim_time)
                hours, remainder = divmod(int(time_left.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                
                await ctx.followup.send(f"Ya reclamaste tu recompensa. Vuelve en **{hours}h {minutes}m**.", ephemeral=True)
                return

        # Si 'last_claim_time' es None o si ya pasaron las 15 horas, se entrega la recompensa.
        await asyncio.to_thread(db.update_lbucks, user_id, 5)
        await asyncio.to_thread(db.update_daily_claim, user_id)
        
        await ctx.followup.send("¡Has reclamado tu recompensa de 5 LBucks! Vuelve en 15 horas. 🪙", ephemeral=True)

    except Exception as e:
        print(f"🚨 Error inesperado en daily_command: {e}")
        await ctx.followup.send("Ocurrió un error al procesar tu recompensa. Por favor, intenta de nuevo más tarde.", ephemeral=True)



@bot.slash_command(
    guild_ids=[GUILD_ID], name="canjear", description="Abre la tienda para canjear LBucks."
)
async def canjear(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    items = await asyncio.to_thread(db.get_shop_items) or []
    await ctx.followup.send("Abriendo el Centro de Canjeo...",
                            view=RedeemMenuView(items),
                            ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID], name="saldo", description="Consulta tu saldo de LBucks."
)
async def saldo(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    balance = await asyncio.to_thread(db.get_balance, ctx.user.id)
    await ctx.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙",
                            view=UpdateBalanceView(),
                            ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID], name="donar", description="Dona LBucks a otro usuario."
)
async def donar(ctx: discord.ApplicationContext):
    await ctx.send_modal(DonateModal())


@bot.slash_command(
    guild_ids=[GUILD_ID], name="misiones", description="Muestra tus misiones diarias."
)
async def misiones(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    missions = await asyncio.to_thread(db.get_daily_missions, ctx.user.id)
    embed = discord.Embed(
        title="📝 Tus Misiones Diarias",
        description="Completa estas misiones para ganar LBucks.",
        color=discord.Color.blue())
    # ... (código del comando sin cambios)
    await ctx.followup.send(embed=embed,
                            view=UpdateMissionsView(),
                            ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID], name="leaderboard", description="Muestra la clasificación de LBucks del servidor."
)
async def leaderboard(ctx: discord.ApplicationContext):
    await ctx.defer()
    
    top_users = await asyncio.to_thread(db.get_lbucks_leaderboard, 10)
    
    embed = discord.Embed(
        title="🏆 Clasificación de LBucks",
        description="¡Los comandantes más ricos de la galaxia!",
        color=discord.Color.gold()
    )
    
    leaderboard_text = ""
    for i, (user_id, lbucks) in enumerate(top_users):
        try:
            user = await bot.fetch_user(int(user_id))
            user_mention = user.mention
        except (discord.NotFound, ValueError):
            user_mention = f"Usuario Desconocido ({user_id})"
        
        emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else "🔹"
        leaderboard_text += f"{emoji} **{i+1}.** {user_mention} - **{lbucks}** LBucks 🪙\n"
        
    if not leaderboard_text:
        leaderboard_text = "Todavía no hay nadie en la clasificación. ¡Sé el primero!"
        
    embed.add_field(name="Top 10 Comandantes", value=leaderboard_text, inline=False)
    await ctx.followup.send(embed=embed)


juegos_group = bot.create_group("juego", "Comandos para iniciar minijuegos", guild_ids=[GUILD_ID])

@juegos_group.command(name="palabra", description="Inicia un juego del ahorcado.")
async def iniciar_juego_palabra(ctx: discord.ApplicationContext):
    await ctx.defer()
    channel_id = ctx.channel.id
    if channel_id in word_games:
        await ctx.followup.send("¡Ya hay una partida en curso en este canal!", ephemeral=True)
        return

    word_to_guess = await get_random_word_local()
    
    word_games[channel_id] = {
        'word': word_to_guess,
        'guessed_letters': set(),
        'wrong_guesses': set(),
        'mistakes': 0,
        'start_time': datetime.datetime.now(),
        'message_id': None
    }
    
    initial_embed = create_hangman_embed(word_games[channel_id])
    game_message = await ctx.followup.send(embed=initial_embed)
    word_games[channel_id]['message_id'] = game_message.id

@juegos_group.command(name="numero", description="Inicia un juego de adivinar el número.")
async def iniciar_juego_numero(ctx: discord.ApplicationContext):
    channel_id = ctx.channel.id
    if channel_id in number_games:
        await ctx.respond("¡Ya hay un juego de adivinar el número en este canal!", ephemeral=True)
        return

    number_games[channel_id] = {
        'number': random.randint(1, 100),
        'start_time': datetime.datetime.now(),
    }
    await ctx.respond(
        "🎉 **¡Nuevo juego de Adivinar el Número!** 🎉\n\n"
        "He pensado en un número del **1 al 100**. Tienen 2 minutos.\n"
        "Usen `/adivinar` para hacer un intento. ¡Suerte!"
    )

@bot.slash_command(
    guild_ids=[GUILD_ID], name="adivinar", description="Adivina el número del juego actual."
)
async def adivinar_numero(ctx: discord.ApplicationContext, numero: int):
    await ctx.defer()
    channel_id = ctx.channel.id
    if channel_id not in number_games:
        await ctx.followup.send("No hay ningún juego de adivinar el número activo. Inícialo con `/juego numero`.", ephemeral=True)
        return

    game = number_games[channel_id]
    
    if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=2):
        await ctx.followup.send(f"¡Se acabó el tiempo! El número era **{game['number']}**. Inicia un nuevo juego.")
        del number_games[channel_id]
        return

    if numero == game['number']:
        reward = 8
        await asyncio.to_thread(db.update_lbucks, ctx.author.id, reward)
        await ctx.followup.send(f"¡Felicidades, {ctx.author.mention}! Adivinaste el número **{game['number']}** y ganaste **{reward} LBucks**. 🥳")
        del number_games[channel_id]
    elif numero < game['number']:
        await ctx.followup.send(f"`{numero}` es muy bajo. El número es **mayor**.")
    else:
        await ctx.followup.send(f"`{numero}` es muy alto. El número es **menor**.")

adventure_group = bot.create_group("aventura", "Comandos para la aventura espacial", guild_ids=[GUILD_ID])

@adventure_group.command(name="iniciar", description="Comienza tu aventura espacial y funda tu estación.")
async def aventura_iniciar(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    
    player = await asyncio.to_thread(db.get_player_profile, ctx.author.id)
    if player:
        await ctx.followup.send("Comandante, ya has iniciado tu aventura. Usa `/aventura perfil` para ver tu estado.", ephemeral=True)
        return
        
    await asyncio.to_thread(db.create_player_profile, ctx.author.id)
    
    intros = [
        "Tras escapar del colapso de la Supernova Kepler, tu cápsula de escape aterriza en un sector desconocido. Con los restos de tu nave, estableces una base precaria. El universo te espera.",
        "Eres un comerciante renegado, buscando fortuna en el Borde Exterior. Has encontrado un asteroide rico en recursos y has decidido que es hora de construir tu propio imperio.",
        "Como último superviviente de la Expedición a Andrómeda, tu misión ahora es sobrevivir. Tu estación es tu único refugio, y tu pequeña nave, tu única esperanza."
    ]
    
    embed = discord.Embed(
        title=f"🚀 Bienvenid@ a la Frontera, Comandante {ctx.author.name}!",
        description=random.choice(intros),
        color=discord.Color.dark_purple()
    )
    embed.add_field(name="Estación Fundada", value=f"Has establecido tu base de operaciones.\n{ASCII_ART['station']}", inline=False)
    embed.add_field(name="Nave Operativa", value=f"Tu nave inicial está lista para explorar.\n{ASCII_ART['intro']}", inline=False)
    embed.set_footer(text="Usa /aventura explorar para buscar tu primer planeta.")
    
    await ctx.followup.send(embed=embed, ephemeral=True)

@adventure_group.command(name="perfil", description="Muestra el estado de tu nave, estación e inventario.")
async def aventura_perfil(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    player = await asyncio.to_thread(db.get_player_profile, ctx.author.id)

    if not player:
        await ctx.followup.send("Aún no has comenzado tu aventura. Usa `/aventura iniciar` para empezar.", ephemeral=True)
        return

    inventory = player['inventory']
    inventory_text = "\n".join([f"- {item['name']}" for item in inventory]) if inventory else "Vacío"

    embed = discord.Embed(title=f"Perfil del Comandante {ctx.author.name}", color=discord.Color.blue())
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.add_field(name="🚀 Nivel de Nave", value=f"**Nivel {player['ship_level']}**", inline=True)
    embed.add_field(name="🏛️ Nivel de Estación", value=f"**Nivel {player['station_level']}**", inline=True)
    embed.add_field(name="💥 Poder de Combate", value=f"**{player['power_level']}**", inline=True)
    embed.add_field(name="📦 Inventario", value=f"```{inventory_text}```", inline=False)
    
    await ctx.followup.send(embed=embed, ephemeral=True)

@adventure_group.command(name="explorar", description="Busca nuevos planetas para conquistar.")
async def aventura_explorar(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    player = await asyncio.to_thread(db.get_player_profile, ctx.author.id)

    if not player:
        await ctx.followup.send("Debes iniciar tu aventura primero con `/aventura iniciar`.", ephemeral=True)
        return

    conquered_list = player['conquered_planets']
    planets = await asyncio.to_thread(db.get_explorable_planets, conquered_list)
    
    if not planets:
        await ctx.followup.send("¡Felicidades, Comandante! Parece que has conquistado toda la galaxia conocida.", ephemeral=True)
        return
        
    embed = discord.Embed(
        title="🔭 Escáner de Largo Alcance Activado",
        description="Se han detectado los siguientes sistemas planetarios. Elige tu próximo objetivo:",
        color=discord.Color.teal()
    )
    
    view = PlanetSelectionView(planets, ctx.author.id)
    await ctx.followup.send(embed=embed, view=view, ephemeral=True)

# --- 6. COMANDOS DE ADMINISTRACIÓN ---
admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role is None or admin_role not in ctx.author.roles:
        await ctx.respond("Este comando es solo para usuarios con el rol de administrador del bot.", ephemeral=True)
        return
        
    await ctx.defer(ephemeral=True)
    await asyncio.to_thread(db.update_lbucks, usuario.id, cantidad)
    action = "añadido" if cantidad >= 0 else "quitado"
    await ctx.followup.send(
        f"Se han **{action} {abs(cantidad)} LBucks** a {usuario.mention}.",
        ephemeral=True)

# --- 7. SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    bot.run(TOKEN)
