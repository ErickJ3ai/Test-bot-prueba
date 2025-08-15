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
from unidecode import unidecode # <-- Se debe añadir a requirements.txt

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = discord.Bot(intents=intents)

# --- 2. LÓGICA DE JUEGOS Y TAREAS DE FONDO ---
word_games = {} # Guardamos el estado del juego por ID del canal

async def get_random_word_from_api():
    """Obtiene una palabra aleatoria de una API externa."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://clientes.api.ilernus.com/randomWord/1") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return unidecode(data[0]['word'].lower())
                else:
                    print(f"Error de API: Status {resp.status}")
                    return None
    except Exception as e:
        print(f"Error al obtener palabra de la API: {e}")
        return None

async def check_word_game_timeout():
    """Tarea en segundo plano que finaliza juegos de palabras si exceden el tiempo."""
    while True:
        await asyncio.sleep(60)
        now = datetime.datetime.now()
        to_delete = []
        for channel_id, game in word_games.items():
            if now - game['start_time'] > datetime.timedelta(minutes=7):
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"¡Se acabó el tiempo para el juego de adivinar! La palabra era **'{game['word']}'**.")
                to_delete.append(channel_id)
        
        for channel_id in to_delete:
            del word_games[channel_id]

# --- 3. COMPONENTES DE UI (VISTAS Y MODALES) ---

class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        self.add_item(discord.ui.InputText(
            label="Cantidad de LBucks",
            placeholder="Introduce la cantidad a donar",
            min_length=1,
            max_length=10,
        ))
        self.add_item(discord.ui.InputText(
            label="Destinatario (ID o nombre de usuario)",
            placeholder="Introduce el ID o nombre#tag del usuario",
            min_length=2,
            max_length=37,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            amount_str = self.children[0].value
            recipient_str = self.children[1].value
            
            amount = int(amount_str)
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

            if recipient is None:
                await interaction.followup.send("No se pudo encontrar al destinatario. Proporciona su ID o nombre de usuario completo.", ephemeral=True)
                return

            if interaction.user.id == recipient.id:
                await interaction.followup.send("No puedes donarte LBucks a ti mismo.", ephemeral=True)
                return

            doner_balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send(f"No tienes suficientes LBucks. Tu saldo es **{doner_balance}**.", ephemeral=True)
                return

            await asyncio.to_thread(db.update_lbucks, interaction.user.id, -amount)
            await asyncio.to_thread(db.update_lbucks, recipient.id, amount)
            
            await interaction.followup.send(f"¡Has donado **{amount} LBucks** a **{recipient.name}**! 🎉", ephemeral=True)
            try:
                await recipient.send(f"¡Buenas noticias! Has recibido una donación de **{amount} LBucks** de parte de **{interaction.user.name}**.")
            except discord.Forbidden:
                pass 

        except ValueError:
            await interaction.followup.send("La cantidad debe ser un número válido.", ephemeral=True)
        except Exception as e:
            print(f"Error en el modal de donación: {e}")
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
        item_id = interaction.data['custom_id'].replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item or item[2] <= 0:
            return await interaction.response.send_message("Este ítem ya no está disponible o se agotó.", ephemeral=True)
        
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.response.send_message(
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

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Confirmar Canje", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        item_data = await asyncio.to_thread(db.get_item, self.item_id)

        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks para este canje.", ephemeral=True)
            return
        
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Qué mala suerte! Alguien más canjeó el último ítem justo ahora.", ephemeral=True)
            return

        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(
                title="⏳ Nuevo Canje Pendiente",
                description=f"El usuario **{interaction.user.name}** (`{interaction.user.id}`) ha canjeado **{robux_amount} Robux**.",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id, self.item_id, log_message.id)
        
        await interaction.followup.send("¡Canjeo solicitado! Un administrador revisará tu solicitud pronto.", ephemeral=True)
        await self.disable_all_items()
        await interaction.edit_original_response(content="Tu solicitud está en proceso.", view=self)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await self.disable_all_items()
        await interaction.response.edit_message(content="Tu canje ha sido cancelado.", view=self)

class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process_action(self, interaction: discord.Interaction, new_status: str):
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.response.send_message("No tienes permiso para realizar esta acción.", ephemeral=True)

        await interaction.response.defer()
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canje ya fue procesado.", view=None, embed=interaction.message.embeds[0])

        await asyncio.to_thread(db.update_redemption_status, redemption[0], new_status)
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        
        original_embed = interaction.message.embeds[0]
        original_embed.add_field(name="Procesado por", value=interaction.user.mention, inline=False)

        if new_status == 'completed':
            try:
                await user.send(f"✅ ¡Tu canje de **{item_name}** ha sido completado y entregado!")
            except discord.Forbidden:
                pass
            original_embed.title = "✅ Canjeo Completado"
            original_embed.color = discord.Color.green()
        else: # cancelled_by_admin
            item = await asyncio.to_thread(db.get_item, redemption[2])
            if item:
                await asyncio.to_thread(db.update_lbucks, redemption[1], item[1])
                await asyncio.to_thread(db.update_stock, redemption[2], 1)
            try:
                await user.send(f"❌ Tu canje de **{item_name}** fue rechazado. Tus LBucks han sido devueltos a tu cuenta.")
            except discord.Forbidden:
                pass
            original_embed.title = "❌ Canjeo Rechazado"
            original_embed.color = discord.Color.red()
        
        await interaction.edit_original_response(embed=original_embed, view=None)

    @discord.ui.button(label="Completar", style=discord.ButtonStyle.success, custom_id="persistent:admin_complete")
    async def complete_button(self, button: Button, interaction: discord.Interaction):
        await self.process_action(interaction, 'completed')

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await self.process_action(interaction, 'cancelled_by_admin')

class UpdateBalanceView(View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(label="🔄 Actualizar Saldo", style=discord.ButtonStyle.primary, custom_id="persistent:update_balance")
    async def update_balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.followup.send(f"Tu saldo actualizado es: **{balance} LBucks** 🪙", ephemeral=True)

# --- 4. EVENTOS DEL BOT ---
invites_cache = {}

@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO")
    await asyncio.to_thread(db.init_db)
    print("✔️ Base de datos inicializada.")

    try:
        await bot.sync_commands()
        print("🔄 Comandos slash sincronizados con Discord.")
    except Exception as e:
        print(f"⚠️ Error al sincronizar comandos: {e}")

    if not hasattr(bot, "persistent_views_added"):
        bot.add_view(AdminActionView())
        bot.add_view(UpdateBalanceView())
        bot.persistent_views_added = True
        print("👁️ Vistas persistentes registradas.")

    print("⏳ Cacheando invitaciones...")
    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            print(f"Error: Faltan permisos para leer invitaciones en {guild.name}")
    print("✔️ Caché de invitaciones completado.")

    bot.loop.create_task(check_word_game_timeout())
    print("🕰️ Tarea de timeout para juegos iniciada.")

@bot.event
async def on_member_join(member):
    await asyncio.sleep(3) 
    try:
        new_invites = await member.guild.invites()
        old_invites = invites_cache.get(member.guild.id, [])
        
        for old in old_invites:
            for new in new_invites:
                if old.code == new.code and new.uses > old.uses:
                    await asyncio.to_thread(db.check_and_update_invite_reward, new.inviter.id, 100)
                    print(f"{new.inviter.name} ha invitado a {member.name}")
                    try:
                        await new.inviter.send(f"¡Gracias por invitar a **{member.name}** al servidor! Has ganado **100 LBucks**.")
                    except discord.Forbidden:
                        pass
                    invites_cache[member.guild.id] = new_invites
                    return
    except Exception as e:
        print(f"Error en on_member_join: {e}")
        invites_cache[member.guild.id] = await member.guild.invites()

@bot.listen("on_message")
async def on_message_handler(message):
    if message.author.bot:
        return

    await asyncio.to_thread(db.update_mission_progress, message.author.id, "message_count")

    if message.channel.id in word_games:
        game = word_games[message.channel.id]
        guess = unidecode(message.content.lower())

        if guess == game['word']:
            reward = 20
            await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
            await message.channel.send(f"¡Correcto, {message.author.mention}! 🥳 La palabra era **'{game['word']}'**. Has ganado **{reward} LBucks**.")
            del word_games[message.channel.id]
        
        elif len(guess) == 1 and guess.isalpha():
            if guess in game['guessed_letters']:
                await message.add_reaction("🤔")
                return

            game['guessed_letters'].add(guess)
            
            if guess in game['word']:
                new_hint = "".join([c if c in game['guessed_letters'] else " _ " for c in game['word']])
                if "_" not in new_hint:
                    reward = 20
                    await asyncio.to_thread(db.update_lbucks, message.author.id, reward)
                    await message.channel.send(f"¡Lo lograste, {message.author.mention}! 🥳 La palabra era **'{game['word']}'**. Has ganado **{reward} LBucks**.")
                    del word_games[message.channel.id]
                else:
                    await message.channel.send(f"¡Sí! La letra '{guess}' está en la palabra: `{new_hint}`")
            else:
                game['rounds'] -= 1
                if game['rounds'] > 0:
                    await message.channel.send(f"Nop, la letra '{guess}' no está. Te quedan **{game['rounds']}** intentos.")
                else:
                    await message.channel.send(f"¡Se acabaron los intentos! La palabra era **'{game['word']}'**. Mejor suerte la próxima vez.")
                    del word_games[message.channel.id]

# --- 5. COMANDOS SLASH ---

@bot.slash_command(guild_ids=[GUILD_ID], name="balance", description="Consulta tu saldo de LBucks.")
async def balance(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    balance = await asyncio.to_thread(db.get_balance, ctx.author.id)
    await ctx.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙", view=UpdateBalanceView(), ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], name="donar", description="Transfiere LBucks a otro usuario.")
async def donate(ctx: discord.ApplicationContext):
    modal = DonateModal()
    await ctx.send_modal(modal)

@bot.slash_command(guild_ids=[GUILD_ID], name="canjear", description="Muestra la tienda para canjear Robux por LBucks.")
async def redeem(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    items = await asyncio.to_thread(db.get_all_items)
    if not items:
        await ctx.followup.send("La tienda está vacía en este momento.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🛍️ Tienda de Canje",
        description="Selecciona un ítem para canjearlo usando tus LBucks.",
        color=discord.Color.blurple()
    )
    view = RedeemMenuView(items)
    await ctx.followup.send(embed=embed, view=view, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], name="invitaciones", description="Muestra cuántas personas has invitado al servidor.")
async def show_invites(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    count = await asyncio.to_thread(db.get_invite_count, ctx.author.id)
    await ctx.followup.send(f"Has invitado a **{count}** personas al servidor. ¡Sigue así! 🚀", ephemeral=True)

game_commands = bot.create_group("jugar", "Comandos para minijuegos", guild_ids=[GUILD_ID])
@game_commands.command(name="palabra", description="Inicia un juego de adivinar la palabra.")
async def guess_word(ctx: discord.ApplicationContext):
    channel_id = ctx.channel.id
    if channel_id in word_games:
        await ctx.respond("Ya hay un juego de adivinar palabras en este canal.", ephemeral=True)
        return

    await ctx.defer()
    word = await get_random_word_from_api()
    if not word:
        await ctx.followup.send("No pude obtener una palabra para jugar. Inténtalo más tarde.", ephemeral=True)
        return

    word_games[channel_id] = {
        'word': word,
        'guessed_letters': set(),
        'start_time': datetime.datetime.now(),
        'rounds': 6
    }
    
    hint = " _ " * len(word)
    await ctx.followup.send(
        f"¡Nuevo juego de adivinar la palabra! Tienes 7 minutos y 6 intentos.\n"
        f"La palabra tiene {len(word)} letras: `{hint}`\n"
        "Envía una letra o la palabra completa para adivinar."
    )

admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

@admin_commands.command(name="add_lbucks", description="Añade o quita LBucks a un usuario.")
@commands.has_role(ADMIN_ROLE_NAME)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    await ctx.defer(ephemeral=True)
    await asyncio.to_thread(db.update_lbucks, usuario.id, cantidad)
    action = "añadido" if cantidad >= 0 else "quitado"
    await ctx.followup.send(f"Se han **{action} {abs(cantidad)} LBucks** a {usuario.mention}.", ephemeral=True)

# --- 6. SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo y funcionando."

def run_web_server():
    serve(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    bot.run(TOKEN)
