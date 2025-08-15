# -*- coding: utf-8 -*-
import discord
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
import aiohttp
from unidecode import unidecode # <-- Añadir a requirements.txt

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = discord.Bot(intents=intents)

# --- 2. GESTIÓN DE JUEGOS Y TAREAS DE FONDO ---
number_games = {}
word_games = {}

async def get_random_word_from_api():
    """Obtiene una palabra aleatoria en español y la normaliza sin acentos."""
    try:
        async with aiohttp.ClientSession() as session:
            # Esta API es más específica para palabras en español.
            async with session.get("https://clientes.api.ilernus.com/randomWord/1") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Normalizamos la palabra a minúsculas y sin acentos para facilitar el juego.
                    return unidecode(data[0]['word'].lower())
                else:
                    return None
    except Exception as e:
        print(f"Error al obtener palabra de la API: {e}")
        return None

async def check_word_game_timeout():
    """Tarea en segundo plano que finaliza juegos si exceden el tiempo límite."""
    while True:
        await asyncio.sleep(60)
        now = datetime.datetime.now()
        to_delete = []
        for channel_id, game in word_games.items():
            if now - game['start_time'] > datetime.timedelta(minutes=7):
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"¡Se acabó el tiempo! La palabra era **'{game['word']}'**.")
                to_delete.append(channel_id)
        
        for channel_id in to_delete:
            if channel_id in word_games:
                del word_games[channel_id]

# --- 3. COMPONENTES DE UI (VISTAS Y MODALES) ---

class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        self.add_item(discord.ui.InputText(
            label="Cantidad de LBucks",
            placeholder="Introduce la cantidad a donar"
        ))
        self.add_item(discord.ui.InputText(
            label="Destinatario (ID o nombre de usuario)",
            placeholder="Introduce el ID o nombre#tag del usuario"
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            amount = int(self.children[0].value)
            recipient_str = self.children[1].value

            if amount <= 0:
                await interaction.followup.send("La cantidad debe ser un número positivo.", ephemeral=True)
                return

            recipient = None
            if recipient_str.isdigit():
                try:
                    recipient = await bot.fetch_user(int(recipient_str))
                except discord.NotFound:
                    pass
            
            if not recipient:
                recipient = discord.utils.get(interaction.guild.members, name=recipient_str.split('#')[0])

            if not recipient or recipient.bot:
                await interaction.followup.send("No se pudo encontrar a ese usuario.", ephemeral=True)
                return

            if interaction.user.id == recipient.id:
                await interaction.followup.send("No puedes donarte a ti mismo.", ephemeral=True)
                return

            doner_balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send(f"No tienes suficientes LBucks. Saldo: {doner_balance}", ephemeral=True)
                return

            await asyncio.to_thread(db.update_lbucks, interaction.user.id, -amount)
            await asyncio.to_thread(db.update_lbucks, recipient.id, amount)
            
            await interaction.followup.send(f"¡Has donado **{amount} LBucks** a **{recipient.name}**! 🎉", ephemeral=True)
        except ValueError:
            await interaction.followup.send("La cantidad debe ser un número válido.", ephemeral=True)
        except Exception as e:
            print(f"Error en modal de donación: {e}")
            await interaction.followup.send("Ocurrió un error al procesar tu donación.", ephemeral=True)

class RedeemMenuView(View):
    def __init__(self, items):
        super().__init__(timeout=300)
        for item_id, price, stock in items:
            robux_amount = item_id.split('_')[0]
            label = f"{robux_amount} Robux ({price} LBucks)"
            button = Button(
                label=label,
                custom_id=f"redeem_{item_id}",
                style=discord.ButtonStyle.blurple,
                disabled=(stock <= 0)
            )
            button.callback = self.handle_redeem_click
            self.add_item(button)

    async def handle_redeem_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        item_id = interaction.data['custom_id'].replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item or item[2] <= 0:
            return await interaction.followup.send("Este ítem ya no está disponible.", ephemeral=True)
        
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.followup.send(
            f"¿Confirmas el canje de **{item[0].split('_')[0]} Robux** por **{item[1]} LBucks**?",
            view=view,
            ephemeral=True
        )

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar Canje", style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.", ephemeral=True)
            return
        
        item_data = await asyncio.to_thread(db.get_item, self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Justo se agotó! Alguien más fue más rápido.", ephemeral=True)
            return

        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(
                title="⏳ Nuevo Canje Pendiente",
                description=f"Usuario: {interaction.user.mention} (`{interaction.user.id}`)\nÍtem: **{robux_amount} Robux**",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id, self.item_id, log_message.id)
        
        await interaction.followup.send("¡Canjeo realizado! Un administrador revisará tu solicitud.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(content="Solicitud procesada.", view=self)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Tu canje ha sido cancelado.", view=self)

class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process_action(self, interaction: discord.Interaction, new_status: str, color: discord.Color):
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.response.send_message("No tienes permiso para esta acción.", ephemeral=True)

        await interaction.response.defer()
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canje ya fue procesado.", view=None)

        await asyncio.to_thread(db.update_redemption_status, redemption[0], new_status)
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        
        edited_embed = interaction.message.embeds[0]
        edited_embed.color = color
        edited_embed.add_field(name="Procesado por", value=interaction.user.mention, inline=False)

        if new_status == 'completed':
            edited_embed.title = "✅ Canjeo Completado"
            dm_message = f"✅ ¡Tu canje de **{item_name}** ha sido completado!"
        else: # cancelled_by_admin
            edited_embed.title = "❌ Canjeo Rechazado por Admin"
            dm_message = f"❌ Tu canje de **{item_name}** fue rechazado. Tus LBucks han sido devueltos."
            item = await asyncio.to_thread(db.get_item, redemption[2])
            if item:
                await asyncio.to_thread(db.update_lbucks, redemption[1], item[1])
                await asyncio.to_thread(db.update_stock, redemption[2], 1)
        
        try:
            await user.send(dm_message)
        except discord.Forbidden:
            pass
        
        await interaction.edit_original_response(embed=edited_embed, view=None)

    @discord.ui.button(label="Completar", style=discord.ButtonStyle.success, custom_id="persistent:admin_complete")
    async def complete_button(self, button: Button, interaction: discord.Interaction):
        await self.process_action(interaction, 'completed', discord.Color.green())

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await self.process_action(interaction, 'cancelled_by_admin', discord.Color.red())

class UpdateBalanceView(View):
    def __init__(self):
        # Vista persistente para que el botón siempre funcione
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Actualizar Saldo", style=discord.ButtonStyle.primary, custom_id="persistent:update_balance")
    async def update_balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.followup.send(f"Tu saldo actualizado es: **{balance} LBucks** 🪙", ephemeral=True)

class UpdateMissionsView(View):
    def __init__(self):
        # Vista persistente
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Actualizar Misiones", style=discord.ButtonStyle.primary, custom_id="persistent:update_missions")
    async def update_missions_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        missions = await asyncio.to_thread(db.get_daily_missions, interaction.user.id)
        if not missions:
            await interaction.followup.send("No hay misiones disponibles.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📝 Tus Misiones Diarias",
            description="Completa estas misiones para ganar LBucks.",
            color=discord.Color.blue()
        )
        for m in missions:
            status_emoji = "✅" if m['is_completed'] else "⌛"
            progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
            embed.add_field(
                name=f"{status_emoji} {m['description']}",
                value=f"Recompensa: **{m['reward']} LBucks** {progress_text}",
                inline=False
            )
        # Usamos followup para una nueva respuesta efímera en lugar de editar.
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

# --- 4. EVENTOS DEL BOT ---
invites_cache = {}

@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")
    
    await asyncio.to_thread(db.init_db)
    print("✔️ Base de datos inicializada.")

    # Sincronizar comandos para que aparezcan en Discord
    await bot.sync_commands()
    print("🔄 Comandos slash sincronizados.")

    if not hasattr(bot, "persistent_views_added"):
        bot.add_view(AdminActionView())
        bot.add_view(UpdateBalanceView())
        bot.add_view(UpdateMissionsView())
        bot.persistent_views_added = True
        print("👁️ Vistas persistentes registradas.")

    print("⏳ Cacheando invitaciones...")
    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            print(f"Error: Permisos faltantes para leer invitaciones en {guild.name}")
    print("✔️ Caché de invitaciones completado.")
    
    bot.loop.create_task(check_word_game_timeout())

@bot.event
async def on_member_join(member):
    await asyncio.sleep(3)
    try:
        current_invites = await member.guild.invites()
        old_invites = invites_cache.get(member.guild.id, [])
        
        for old_invite in old_invites:
            for new_invite in current_invites:
                if old_invite.code == new_invite.code and new_invite.uses > old_invite.uses:
                    await asyncio.to_thread(db.check_and_update_invite_reward, new_invite.inviter.id, 100) # Recompensa
                    invites_cache[member.guild.id] = current_invites
                    return
    except Exception as e:
        print(f"Error en on_member_join: {e}")
    finally:
        invites_cache[member.guild.id] = await member.guild.invites()

# --- 5. LISTENERS PARA MISIONES Y JUEGOS ---

@bot.listen("on_message")
async def mission_message_tracker(message):
    if message.author.bot:
        return
    await asyncio.to_thread(db.update_mission_progress, message.author.id, "message_count")

@bot.listen("on_message")
async def guess_word_listener(message):
    if message.author.bot or message.content.startswith('/'):
        return

    channel_id = message.channel.id
    if channel_id in word_games:
        game = word_games[channel_id]
        guess = unidecode(message.content.lower())

        if guess == game['word']:
            reward = 20
            await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
            await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra **'{game['word']}'** y ganaste **{reward} LBucks**. 🥳")
            del word_games[message.channel.id]
        elif len(guess) == 1 and guess.isalpha():
            if guess in game['guessed_letters']:
                return

            game['guessed_letters'].add(guess)
            
            if guess in game['word']:
                new_hint = " ".join([c if c in game['guessed_letters'] else "_" for c in game['word']])
                if "_" not in new_hint.replace(" ", ""):
                    reward = 20
                    await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
                    await message.channel.send(f"¡Completaste la palabra, {message.author.mention}! Era **'{game['word']}'**. Ganaste **{reward} LBucks**. 🥳")
                    del word_games[message.channel.id]
                else:
                    await message.channel.send(f"¡Correcto! La letra '{guess}' está. Pista: `{new_hint}`")
            else:
                game['rounds'] -= 1
                if game['rounds'] > 0:
                    await message.channel.send(f"La letra '{guess}' no está. Te quedan **{game['rounds']}** intentos.")
                else:
                    await message.channel.send(f"¡Se acabaron los intentos! La palabra era **'{game['word']}'**.")
                    del word_games[message.channel.id]

# --- 6. COMANDOS SLASH ---

@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="ayuda",
    description="Muestra el menú principal y la información del bot."
)
async def ayuda(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(
        title="📚 Guía de Comandos",
        description="Aquí tienes todos los comandos disponibles para el bot.",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.add_field(name="☀️ `/login_diario`", value="Reclama 5 LBucks cada 24 horas.", inline=False)
    embed.add_field(name="🏪 `/canjear`", value="Abre la tienda para intercambiar LBucks por premios.", inline=False)
    embed.add_field(name="💵 `/saldo`", value="Consulta tu saldo de LBucks.", inline=False)
    embed.add_field(name="🎁 `/donar`", value="Dona LBucks a otro usuario.", inline=False)
    embed.add_field(name="📝 `/misiones`", value="Consulta tus misiones diarias para ganar recompensas.", inline=False)
    embed.add_field(name="🕹️ `/adivinar_numero`", value="Inicia un juego para adivinar un número.", inline=False)
    embed.add_field(name="📚 `/adivinar_palabra`", value="Inicia una partida para adivinar una palabra.", inline=False)
    embed.add_field(name="👤 `/invitaciones`", value="Revisa cuántas personas has invitado.", inline=False)
    embed.set_footer(text=f"Bot de {ctx.guild.name}")
    await ctx.followup.send(embed=embed, ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="login_diario",
    description="Reclama tu recompensa diaria de 5 LBucks."
)
async def daily_command(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    try:
        user_id = ctx.user.id
        user_data = await asyncio.to_thread(db.get_user, user_id)
        if user_data is None:
            await ctx.followup.send("Error al obtener tus datos, intenta de nuevo.", ephemeral=True)
            return

        last_claim_time = user_data[2]
        # Asegurarse de que la fecha y hora tiene timezone para una comparación correcta
        if isinstance(last_claim_time, str):
            last_claim_time = datetime.datetime.fromisoformat(last_claim_time).replace(tzinfo=datetime.timezone.utc)
        
        if last_claim_time and (datetime.datetime.now(datetime.timezone.utc) - last_claim_time < datetime.timedelta(hours=24)):
            time_left = datetime.timedelta(hours=24) - (datetime.datetime.now(datetime.timezone.utc) - last_claim_time)
            hours, rem = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
            await ctx.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.", ephemeral=True)
            return

        await asyncio.to_thread(db.update_lbucks, user_id, 5)
        await asyncio.to_thread(db.update_daily_claim, user_id)
        await ctx.followup.send("¡Has reclamado tus 5 LBucks diarios! 🪙", ephemeral=True)
    except Exception as e:
        print(f"Error en daily_command: {e}")
        await ctx.followup.send("Ocurrió un error al procesar tu recompensa.", ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="canjear",
    description="Abre la tienda para canjear LBucks por Robux."
)
async def canjear(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    items = await asyncio.to_thread(db.get_shop_items) or []
    if not items:
        await ctx.followup.send("La tienda está vacía en este momento.", ephemeral=True)
        return
    await ctx.followup.send("🏪 **Tienda de Canje**", view=RedeemMenuView(items), ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="saldo",
    description="Consulta tu saldo actual de LBucks."
)
async def saldo(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    balance = await asyncio.to_thread(db.get_balance, ctx.user.id)
    await ctx.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙", view=UpdateBalanceView(), ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="donar",
    description="Dona LBucks a otro usuario."
)
async def donar(ctx: discord.ApplicationContext):
    await ctx.send_modal(DonateModal())


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="misiones",
    description="Muestra tus misiones diarias."
)
async def misiones(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    missions = await asyncio.to_thread(db.get_daily_missions, ctx.user.id)
    embed = discord.Embed(
        title="📝 Tus Misiones Diarias",
        description="Completa estas misiones para ganar LBucks.",
        color=discord.Color.blue()
    )
    if not missions:
        embed.description = "No hay misiones disponibles en este momento."
    else:
        for m in missions:
            status_emoji = "✅" if m['is_completed'] else "⌛"
            progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
            embed.add_field(
                name=f"{status_emoji} {m['description']}",
                value=f"Recompensa: **{m['reward']} LBucks** {progress_text}",
                inline=False
            )
    await ctx.followup.send(embed=embed, view=UpdateMissionsView(), ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="adivinar_numero",
    description="Inicia un juego para adivinar un número y ganar LBucks."
)
async def guess_number_game(ctx: discord.ApplicationContext, intento: int):
    channel_id = ctx.channel.id
    user_id = ctx.author.id

    if channel_id not in number_games:
        await ctx.respond("No hay un juego de adivinar el número en este canal. ¡Inicia uno nuevo!", ephemeral=True)
        return

    game = number_games[channel_id]
    
    if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=1):
        await ctx.respond(f"¡Se acabó el tiempo! El número era **{game['number']}**.", ephemeral=False)
        del number_games[channel_id]
        return

    if intento == game['number']:
        reward = 8
        await asyncio.to_thread(db.update_lbucks, user_id, reward)
        await ctx.respond(f"¡Felicidades, {ctx.author.mention}! Adivinaste el número **{game['number']}** y ganaste **{reward} LBucks**. 🥳", ephemeral=False)
        del number_games[channel_id]
    elif intento < game['number']:
        await ctx.respond("El número es **mayor**.", ephemeral=False)
    else:
        await ctx.respond("El número es **menor**.", ephemeral=False)

@guess_number_game.before_invoke
async def before_guess_number(ctx: discord.ApplicationContext):
    # Esta función se ejecuta antes para iniciar el juego si no existe
    if ctx.channel.id not in number_games:
        number_games[ctx.channel.id] = {
            'number': random.randint(1, 100),
            'start_time': datetime.datetime.now(),
        }
        await ctx.respond(f"¡Juego nuevo! He pensado en un número del 1 al 100. Tienen 1 minuto para adivinarlo usando `/adivinar_numero [número]`.", ephemeral=False)
        # Detiene la ejecución del comando principal para que el usuario pueda adivinar
        raise commands.CheckFailure()

@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="adivinar_palabra",
    description="Inicia una partida para adivinar una palabra oculta."
)
async def guess_word_game(ctx: discord.ApplicationContext):
    channel_id = ctx.channel.id
    if channel_id in word_games:
        await ctx.respond("¡Ya hay una partida en curso en este canal!", ephemeral=True)
        return
    
    await ctx.defer()
    word_to_guess = await get_random_word_from_api()
    if not word_to_guess:
        await ctx.followup.send("No se pudo obtener una palabra. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    word_games[channel_id] = {
        'word': word_to_guess,
        'guessed_letters': set(),
        'start_time': datetime.datetime.now(),
        'rounds': 6, # Reducido para un juego más rápido
    }
    
    hint = " ".join(["_" for _ in word_to_guess])
    await ctx.followup.send(
        f"¡Nuevo juego de adivinar la palabra! Tienen 7 minutos y 6 intentos.\n"
        f"La palabra tiene **{len(word_to_guess)}** letras: `{hint}`\n"
        "Envía una letra o la palabra completa en el chat para adivinar."
    )


@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="invitaciones",
    description="Muestra la cantidad de personas que has invitado."
)
async def show_invites(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    invites_count = await asyncio.to_thread(db.get_invite_count, ctx.author.id)
    await ctx.followup.send(f"Has invitado a **{invites_count}** personas al servidor. ¡Sigue así! 🚀", ephemeral=True)


# --- COMANDOS DE ADMINISTRACIÓN ---
admin_commands = bot.create_group(
    "admin",
    "Comandos de administración",
    guild_ids=[GUILD_ID]
)

@admin_commands.command(
    name="add_lbucks",
    description="Añade o quita LBucks a un usuario."
)
@commands.has_role(ADMIN_ROLE_NAME)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    await ctx.defer(ephemeral=True)
    await asyncio.to_thread(db.update_lbucks, usuario.id, cantidad)
    action = "añadido" if cantidad >= 0 else "quitado"
    await ctx.followup.send(f"Se han **{action} {abs(cantidad)} LBucks** a {usuario.mention}.", ephemeral=True)

@add_lbucks.error
async def add_lbucks_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.respond("No tienes el rol de administrador para usar este comando.", ephemeral=True)

# --- 7. SERVIDOR WEB Y EJECUCIÓN ---

app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo y funcionando."

def run_web_server():
    # Obtiene el puerto de la variable de entorno PORT, o usa 8080 si no existe.
    port = int(os.environ.get('PORT', 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    bot.run(TOKEN)
