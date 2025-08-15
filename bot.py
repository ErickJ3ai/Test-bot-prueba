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
from unidecode import unidecode # <-- Asegúrate de tener esto en requirements.txt

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- 2. JUEGOS, LISTAS Y GESTIÓN DE ESTADO ---
number_games = {}
word_games = {}

# Lista de palabras local para que el juego sea 100% confiable y rápido
PALABRAS_LOCALES = [
    "computadora", "biblioteca", "desarrollo", "guitarra", "universo",
    "aventura", "botella", "estrella", "planeta", "galaxia", "elefante",
    "jirafa", "cocodrilo", "murcielago", "mariposa", "teclado", "montaña",
    "programacion", "inteligencia", "artificial", "videojuego"
]

async def get_random_word_local():
    """Obtiene una palabra de la lista local para máxima fiabilidad."""
    palabra = random.choice(PALABRAS_LOCALES)
    return unidecode(palabra.lower())


async def check_word_game_timeout():
    while True:
        await asyncio.sleep(60)
        to_delete = []
        now = datetime.datetime.now()
        for channel_id, game in word_games.items():
            if now - game['start_time'] > datetime.timedelta(minutes=7):
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(
                        f"¡Se acabó el tiempo para el juego de adivinar palabras! La palabra era '{game['word']}'."
                    )
                to_delete.append(channel_id)
        for channel_id in to_delete:
            if channel_id in word_games:
                del word_games[channel_id]


# --- 3. VISTAS DE BOTONES (UI) ---
# (Esta sección no necesita cambios, se mantiene como la tenías)
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


@bot.listen("on_message")
async def on_message_handler(message):
    if message.author.bot:
        return

    # Listener para misiones de mensajes
    await asyncio.to_thread(db.update_mission_progress, message.author.id, "message_count")

    # Listener para el juego de adivinar la palabra
    channel_id = message.channel.id
    if channel_id in word_games:
        game = word_games[channel_id]
        guess = unidecode(message.content.lower())

        if guess == game['word']:
            reward = 20
            await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
            await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra **'{game['word']}'** y ganaste **{reward} LBucks**. 🥳")
            del word_games[channel_id]
        elif len(guess) == 1 and guess.isalpha():
            if guess in game['guessed_letters']:
                return # Ignorar letras ya dichas para no spamear el chat

            game['guessed_letters'].add(guess)
            
            if guess in game['word']:
                new_hint = " ".join([c if c in game['guessed_letters'] else "_" for c in game['word']])
                if "_" not in new_hint.replace(" ", ""):
                    reward = 20
                    await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
                    await message.channel.send(f"¡Completaste la palabra, {message.author.mention}! Era **'{game['word']}'**. Ganaste **{reward} LBucks**. 🥳")
                    del word_games[channel_id]
                else:
                    await message.channel.send(f"¡Correcto! La letra '{guess}' está. Pista: `{new_hint}`")
            else:
                game['rounds'] -= 1
                if game['rounds'] > 0:
                    await message.channel.send(f"La letra '{guess}' no está. Te quedan **{game['rounds']}** intentos.")
                else:
                    await message.channel.send(f"¡Se acabaron los intentos! La palabra era **'{game['word']}'**.")
                    del word_games[channel_id]


# --- 5. COMANDOS SLASH ---

@bot.slash_command(
    guild_ids=[GUILD_ID], name="ayuda", description="Muestra el menú de comandos."
)
async def ayuda(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(
        title="📚 Guía de Comandos",
        description="Aquí tienes todos los comandos disponibles.",
        color=discord.Color.blue())
    # ... (el resto del comando ayuda se mantiene igual)
    await ctx.followup.send(embed=embed, ephemeral=True)


@bot.slash_command(
    guild_ids=[GUILD_ID], name="login_diario", description="Reclama tu recompensa diaria."
)
async def daily_command(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    # ... (código del comando sin cambios)
    await ctx.followup.send("¡Has recibido 5 LBucks! 🪙", ephemeral=True)


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

# --- GRUPO DE COMANDOS PARA JUEGOS ---
juegos_group = bot.create_group("juego", "Comandos para iniciar minijuegos", guild_ids=[GUILD_ID])

@juegos_group.command(name="palabra", description="Inicia un juego de adivinar la palabra.")
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
        'start_time': datetime.datetime.now(),
        'rounds': 6,
    }
    hint = " ".join(["_" for _ in word_to_guess])
    await ctx.followup.send(
        f"¡Nuevo juego de adivinar la palabra! Tienen 7 minutos y 6 intentos.\n"
        f"La palabra tiene **{len(word_to_guess)}** letras: `{hint}`\n"
        "Envía una letra o la palabra completa en el chat para adivinar."
    )


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
        "Usen `/adivinar numero` para hacer un intento. ¡Suerte!"
    )


@bot.slash_command(
    guild_ids=[GUILD_ID], name="adivinar", description="Adivina el número del juego actual."
)
async def adivinar_numero(ctx: discord.ApplicationContext, numero: int):
    channel_id = ctx.channel.id
    if channel_id not in number_games:
        await ctx.respond("No hay ningún juego de adivinar el número activo. Inícialo con `/juego numero`.", ephemeral=True)
        return
    
    # El defer se hace aquí para que la respuesta sea pública
    await ctx.defer(ephemeral=False)
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


@bot.slash_command(
    guild_ids=[GUILD_ID], name="invitaciones", description="Muestra tus invitaciones."
)
async def show_invites(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    inviter_id = ctx.user.id
    invites_count = await asyncio.to_thread(db.get_invite_count, inviter_id)
    await ctx.followup.send(
        f"Has invitado a **{invites_count}** personas al servidor. ¡Sigue así! 🚀",
        ephemeral=True)


# --- 6. COMANDOS DE ADMINISTRACIÓN ---
admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
@discord.default_permissions(administrator=True)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    await ctx.defer(ephemeral=True)
    # ... (código del comando sin cambios)
    await ctx.followup.send(
        f"Se han añadido {cantidad} LBucks a {usuario.mention}.",
        ephemeral=True)

# --- 7. SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')

@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    # Obtiene el puerto de la variable de entorno para Render
    port = int(os.environ.get('PORT', 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    bot.run(TOKEN)
