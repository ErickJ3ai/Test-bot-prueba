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
import unicodedata

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- JUEGOS Y ESTADO ---
number_games = {}
word_games = {}

def normalize_text(text):
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')
    text = text.replace(" ", "")
    return text

async def get_random_word_from_api():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://random-word-api.herokuapp.com/word?number=1&lang=es") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return normalize_text(data[0])
                else:
                    return None
    except Exception as e:
        print(f"Error al obtener palabra de la API: {e}")
        return None

async def check_word_game_timeout():
    while True:
        await asyncio.sleep(60)
        to_delete = []
        for channel_id, game in word_games.items():
            if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=7):
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"¡Se acabó el tiempo para el juego de adivinar palabras! La palabra era '{game['word']}'.")
                to_delete.append(channel_id)
        for channel_id in to_delete:
            del word_games[channel_id]

# --- VISTAS Y MODALES ---
class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        self.amount_input = discord.ui.InputText(label="Cantidad de LBucks", placeholder="Introduce la cantidad", min_length=1, max_length=10)
        self.recipient_input = discord.ui.InputText(label="Destinatario (ID o nombre)", placeholder="ID o nombre de usuario", min_length=1, max_length=32)
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
                recipient = discord.utils.get(interaction.guild.members, name=recipient_str)
            if recipient is None:
                await interaction.followup.send("No se pudo encontrar al destinatario.", ephemeral=True)
                return
            if amount <= 0:
                await interaction.followup.send("La cantidad debe ser positiva.", ephemeral=True)
                return
            if interaction.user.id == recipient.id:
                await interaction.followup.send("No puedes donarte a ti mismo.", ephemeral=True)
                return
            doner_balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send("No tienes suficientes LBucks.", ephemeral=True)
                return
            await asyncio.to_thread(db.update_lbucks, interaction.user.id, -amount)
            await asyncio.to_thread(db.update_lbucks, recipient.id, amount)
            await interaction.followup.send(f"Has donado **{amount} LBucks** a **{recipient.name}**. 🎉", ephemeral=True)
        except ValueError:
            await interaction.followup.send("La cantidad debe ser un número válido.", ephemeral=True)
        except Exception as e:
            print(f"Error en modal de donación: {e}")
            await interaction.followup.send("Ocurrió un error al procesar la donación.", ephemeral=True)

# --- RECOMPENSAS, ADMIN, ACTUALIZACIÓN DE SALDO Y MISIONES ---
class RedeemMenuView(View):
    def __init__(self, items):
        super().__init__(timeout=300)
        self.items = items
        for i, (item_id, price, stock) in enumerate(self.items):
            robux_amount = item_id.split('_')[0]
            label = f"{robux_amount} ⏣ ({price} LBucks)"
            button = Button(label=label, custom_id=f"redeem_{item_id}", style=discord.ButtonStyle.blurple, disabled=(stock <= 0))
            button.callback = self.handle_redeem_click
            self.add_item(button)

    async def handle_redeem_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        custom_id = interaction.data['custom_id']
        item_id = custom_id.replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item:
            return await interaction.followup.send("Este item ya no existe.", ephemeral=True)
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.followup.send(f"¿Confirmas canje de **{item[0].split('_')[0]} Robux** por **{item[1]} LBucks**?", view=view, ephemeral=True)

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        item_data = await asyncio.to_thread(db.get_item, self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Se agotó el item!", ephemeral=True)
            return
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.", ephemeral=True)
            return
        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(title="⏳ Nuevo Canjeo Pendiente",
                                  description=f"Usuario **{interaction.user.name}** ({interaction.user.id}) canjeó **{robux_amount} Robux**",
                                  color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id, self.item_id, log_message.id)
        await interaction.followup.send("¡Canjeo realizado! Un admin lo revisará.", ephemeral=True)
        await interaction.edit_original_response(content="Procesando...", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Canje cancelado.", view=None)

class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Completar", style=discord.ButtonStyle.success, custom_id="persistent:admin_complete")
    async def complete_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.", ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)
        await asyncio.to_thread(db.update_redemption_status, redemption[0], 'completed')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(f"✅ Tu canjeo de **{item_name}** ha sido completado!")
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "✅ Canjeo Completado"
        edited_embed.color = discord.Color.green()
        edited_embed.add_field(name="Procesado por", value=interaction.user.mention, inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.", ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)
        item = await asyncio.to_thread(db.get_item, redemption[2])
        if item:
            await asyncio.to_thread(db.update_lbucks, redemption[1], item[1])
            await asyncio.to_thread(db.update_stock, redemption[2], 1)
        await asyncio.to_thread(db.update_redemption_status, redemption[0], 'cancelled_by_admin')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(f"❌ Tu canjeo de **{item_name}** fue cancelado. Tus LBucks fueron devueltos.")
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "❌ Canjeo Cancelado por Admin"
        edited_embed.color = discord.Color.dark_grey()
        edited_embed.add_field(name="Cancelado por", value=interaction.user.mention, inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

class UpdateBalanceView(View):
    def __init__(self):
        super().__init__(timeout=300)
    @discord.ui.button(label="🔄 Actualizar Saldo", style=discord.ButtonStyle.blurple, custom_id="update:balance")
    async def update_balance_button(self, button: Button, interaction: discord.Interaction):
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.response.edit_message(content=f"Tu saldo actual es: **{balance} LBucks** 🪙", view=self)

class UpdateMissionsView(View):
    def __init__(self):
        super().__init__(timeout=300)
    @discord.ui.button(label="🔄 Actualizar Misiones", style=discord.ButtonStyle.blurple, custom_id="update:missions")
    async def update_missions_button(self, button: Button, interaction: discord.Interaction):
        missions = await asyncio.to_thread(db.get_daily_missions, interaction.user.id)
        if not missions:
            await interaction.response.send_message("No hay misiones disponibles.", ephemeral=True)
            return
        embed = discord.Embed(title="📝 Tus Misiones Diarias", description="Completa estas misiones para ganar LBucks.", color=discord.Color.blue())
        for m in missions:
            status_emoji = "✅" if m['is_completed'] else "⌛"
            progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
            embed.add_field(name=f"{status_emoji} {m['description']}", value=f"Recompensa: **{m['reward']} LBucks** {progress_text}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

# --- INVITACIONES ---
invites_cache = {}
@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")
    try:
        await asyncio.to_thread(db.init_db)
        print("✔️ Base de datos inicializada.")
    except Exception as e:
        print(f"⚠️ Error al inicializar DB: {e}")
    try:
        if not hasattr(bot, "persistent_views_added"):
            bot.add_view(AdminActionView())
            bot.add_view(UpdateBalanceView())
            bot.add_view(UpdateMissionsView())
            bot.persistent_views_added = True
    except Exception as e:
        print(f"⚠️ Error al registrar vistas persistentes: {e}")
    # Caché de invitaciones
    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            print(f"Error permisos invitaciones: {guild.name}")
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

# --- MANEJADOR DE MENSAJES PARA ADIVINAR PALABRAS Y NÚMEROS ---
@bot.listen("on_message")
async def guess_listener(message):
    if message.author.bot:
        return

    channel_id = message.channel.id
    user_id = message.author.id

    # --- JUEGO ADIVINAR PALABRAS ---
    if channel_id in word_games:
        game = word_games[channel_id]
        if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=7):
            await message.channel.send(f"⏰ Se acabó el tiempo. La palabra era '{game['word']}'.")
            del word_games[channel_id]
            return

        guess = normalize_text(message.content)
        if len(guess) == 1 and guess.isalpha():  # letra
            if guess in game['guessed_letters']:
                return  # No repetir mensaje
            game['guessed_letters'].add(guess)
            new_hint = "".join([c if c in game['guessed_letters'] else "_" for c in game['word']])
            if guess not in game['word']:
                game['tries'] -= 1
            if "_" not in new_hint:
                reward = 15
                await asyncio.to_thread(db.update_lbucks, user_id, reward)
                await message.channel.send(f"🎉 ¡Correcto! La palabra era '{game['word']}'. Has ganado **{reward} LBucks**.")
                del word_games[channel_id]
            else:
                await message.channel.send(f"Palabra: `{new_hint}`\nIntentos restantes: {game['tries']}")
                if game['tries'] <= 0:
                    await message.channel.send(f"💀 Se acabaron los intentos. La palabra era '{game['word']}'.")
                    del word_games[channel_id]
        elif len(guess) > 1:  # palabra completa
            if guess == game['word']:
                reward = 15
                await asyncio.to_thread(db.update_lbucks, user_id, reward)
                await message.channel.send(f"🎉 ¡Correcto! La palabra era '{game['word']}'. Has ganado **{reward} LBucks**.")
                del word_games[channel_id]
            else:
                game['tries'] -= 1
                if game['tries'] <= 0:
                    await message.channel.send(f"💀 Se acabaron los intentos. La palabra era '{game['word']}'.")
                    del word_games[channel_id]
                else:
                    await message.channel.send(f"❌ Palabra incorrecta. Intentos restantes: {game['tries']}")

    # --- JUEGO ADIVINAR NÚMERO ---
    if channel_id in number_games:
        game = number_games[channel_id]
        if not message.content.isdigit():
            return
        guess = int(message.content)
        game['intentos'] -= 1
        if guess == game['numero']:
            reward = 20
            await asyncio.to_thread(db.update_lbucks, user_id, reward)
            await message.channel.send(f"🎉 ¡Correcto, {message.author.mention}! El número era {game['numero']} y has ganado **{reward} LBucks**.")
            del number_games[channel_id]
        else:
            if game['intentos'] <= 0:
                await message.channel.send(f"💀 Se acabaron los intentos. El número era {game['numero']}.")
                del number_games[channel_id]
            else:
                pista = "mayor" if guess < game['numero'] else "menor"
                barra = "🟩" * game['intentos'] + "🟥" * (12 - game['intentos'])
                await message.channel.send(f"❌ Incorrecto, {message.author.mention}. El número es {pista}.\nIntentos restantes: {game['intentos']}\n{barra}")

# --- COMANDOS DE INICIO DE JUEGO ---
@bot.slash_command(guild_ids=[GUILD_ID], name="adivinar_palabra", description="Inicia un juego de adivinar palabras.")
async def start_word_game(ctx: discord.ApplicationContext):
    channel_id = ctx.channel.id
    if channel_id in word_games:
        await ctx.respond("Ya hay un juego de palabras en curso en este canal.", ephemeral=True)
        return
    palabra = await get_random_word_from_api()
    if not palabra:
        await ctx.respond("No se pudo obtener una palabra. Intenta más tarde.", ephemeral=True)
        return
    word_games[channel_id] = {
        'word': palabra,
        'guessed_letters': set(),
        'tries': 12,
        'start_time': datetime.datetime.now(),
        'started_by': ctx.user.id
    }
    hint = "_" * len(palabra)
    await ctx.respond(f"🎯 Juego iniciado por {ctx.user.mention}!\nPalabra: `{hint}`\nTienes 12 intentos.")

@bot.slash_command(guild_ids=[GUILD_ID], name="adivinar_numero", description="Inicia un juego de adivinar un número entre 1 y 100.")
async def start_number_game(ctx: discord.ApplicationContext):
    channel_id = ctx.channel.id
    if channel_id in number_games:
        await ctx.respond("Ya hay una partida de número en curso en este canal!", ephemeral=True)
        return
    numero_objetivo = random.randint(1, 100)
    number_games[channel_id] = {
        'numero': numero_objetivo,
        'intentos': 12,
        'started_by': ctx.user.id
    }
    barra = "🟩" * 12
    await ctx.respond(f"🎯 Partida iniciada por {ctx.user.mention}! Adivina el número entre 1 y 100. Tienes 12 intentos.\n{barra}")

# --- EJECUCIÓN DEL BOT ---
bot.run(TOKEN)
