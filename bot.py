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

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- JUEGOS Y GESTIÓN DE ESTADO ---
# El estado de los juegos ahora se guarda por el ID del canal, no del usuario.
number_games = {}
word_games = {}

async def get_random_word_from_api():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://random-word-api.herokuapp.com/word?number=1&lang=es") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data[0]
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
            
# --- VISTAS DE BOTONES (UI) ---
class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        self.amount_input = discord.ui.InputText(
            label="Cantidad de LBucks",
            placeholder="Introduce la cantidad a donar",
            min_length=1,
            max_length=10,
            style=discord.InputTextStyle.short
        )
        self.recipient_input = discord.ui.InputText(
            label="Destinatario (ID o nombre de usuario)",
            placeholder="Introduce el ID o nombre de usuario de la persona",
            min_length=1,
            max_length=32,
            style=discord.InputTextStyle.short
        )
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
                await interaction.followup.send("La cantidad a donar debe ser un número positivo.", ephemeral=True)
                return
            if interaction.user.id == recipient.id:
                await interaction.followup.send("No puedes donarte LBucks a ti mismo.", ephemeral=True)
                return
            doner_balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send("No tienes suficientes LBucks para donar.", ephemeral=True)
                return
            await asyncio.to_thread(db.update_lbucks, interaction.user.id, -amount)
            await asyncio.to_thread(db.update_lbucks, recipient.id, amount)
            await interaction.followup.send(f"Has donado **{amount} LBucks** a **{recipient.name}**. ¡Gracias por tu generosidad! 🎉", ephemeral=True)
        except ValueError:
            await interaction.followup.send("La cantidad debe ser un número válido.", ephemeral=True)
        except Exception as e:
            print(f"Error en el modal de donación: {e}")
            await interaction.followup.send("Ocurrió un error al procesar tu donación. Intenta de nuevo más tarde.", ephemeral=True)

class RedeemMenuView(View):
    def __init__(self, items):
        super().__init__(timeout=300)
        self.items = items
        for i, (item_id, price, stock) in enumerate(self.items):
            robux_amount = item_id.split('_')[0]
            label = f"{robux_amount} ⏣ ({price} LBucks)"
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
        custom_id = interaction.data['custom_id']
        item_id = custom_id.replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item:
            return await interaction.followup.send("Este item ya no existe.", ephemeral=True)
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.followup.send(f"¿Confirmas el canje de **{item[0].split('_')[0]} Robux** "f"por **{item[1]} LBucks**?", view=view, ephemeral=True)

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar Canjeo", style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        item_data = await asyncio.to_thread(db.get_item, self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Justo se agotó! Alguien más fue más rápido.")
            return
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.")
            return
        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(title="⏳ Nuevo Canjeo Pendiente", description=f"El usuario **{interaction.user.name}** ({interaction.user.id}) ha canjeado **{robux_amount} Robux**.", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id, self.item_id, log_message.id)
        await interaction.followup.send("¡Canjeo realizado! Un administrador revisará tu solicitud.")
        await interaction.edit_original_response(content="Procesando...", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Tu canjeo ha sido cancelado.", view=None)

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
            await user.send(f"✅ ¡Tu canjeo de **{item_name}** ha sido completado!")
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
            await user.send(f"❌ Tu canjeo de **{item_name}** fue cancelado. Tus LBucks han sido devueltos.")
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
            await interaction.response.send_message("No hay misiones disponibles en este momento. Inténtalo más tarde.", ephemeral=True)
            return
        embed = discord.Embed(title="📝 Tus Misiones Diarias", description="Completa estas misiones para ganar LBucks.", color=discord.Color.blue())
        for m in missions:
            status_emoji = "✅" if m['is_completed'] else "⌛"
            progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
            embed.add_field(name=f"{status_emoji} {m['description']}", value=f"Recompensa: **{m['reward']} LBucks** {progress_text}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

# --- RECOMPENSAS POR INVITACIÓN ---
invites_cache = {}
@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")
    try:
        await asyncio.to_thread(db.init_db)
        print("✔️ Base de datos inicializada.")
    except Exception as e:
        print(f"⚠️ Error al inicializar la base de datos: {e}")
    try:
        if not hasattr(bot, "persistent_views_added"):
            bot.add_view(AdminActionView())
            bot.add_view(UpdateBalanceView())
            bot.add_view(UpdateMissionsView())
            bot.persistent_views_added = True
            print("👁️ Vistas persistentes registradas.")
    except Exception as e:
        print(f"⚠️ Error al registrar vistas persistentes: {e}")

    print("Caché de invitaciones...")
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


# --- MANEJADOR DE COMPONENTES CON CUSTOM_ID ---
@bot.listen("on_message")
async def mission_message_tracker(message):
    user_id = message.author.id
    if message.author.bot:
        return
    await asyncio.to_thread(db.update_mission_progress, user_id, "message_count")

    # Lógica para el juego de adivinar la palabra
    if message.channel.id in word_games:
        game = word_games[message.channel.id]
        
        if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=7):
            await message.channel.send(f"¡Se acabó el tiempo o las rondas para el juego de adivinar palabras de {message.author.mention}! La palabra era '{game['word']}'.")
            del word_games[message.channel.id]
            return
        
        guess = message.content.lower()

        if len(guess) == 1 and guess.isalpha(): # El usuario adivinó una letra
            if guess in game['guessed_letters']:
                await message.channel.send("¡Ya adivinaste esa letra! Intenta con otra.")
                return
            
            game['guessed_letters'].add(guess)
            new_hint = "".join([c if c in game['guessed_letters'] else "_" for c in game['word']])
            
            if guess in game['word']:
                if "_" not in new_hint:
                    reward = 20
                    await asyncio.to_thread(db.update_lbucks, user_id, reward)
                    await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra '{game['word']}' y has ganado **{reward} LBucks**. 🥳")
                    del word_games[channel_id]
                else:
                    await message.channel.send(f"¡Bien hecho, {message.author.mention}! La palabra es: `{new_hint}`")
            else:
                await message.channel.send(f"¡Incorrecto, {message.author.mention}! La letra '{guess}' no está en la palabra. La palabra es: `{new_hint}`")
                game['rounds'] -= 1
                if game['rounds'] > 0:
                    await message.channel.send(f"Te quedan {game['rounds']} rondas.")
                else:
                    await message.channel.send(f"¡Se acabaron las rondas! La palabra era '{game['word']}'.")
                    del word_games[channel_id]

        elif guess == game['word']: # El usuario adivinó la palabra completa
            reward = 20
            await asyncio.to_thread(db.update_lbucks, user_id, reward)
            await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra '{game['word']}' y has ganado **{reward} LBucks**. 🥳")
            del word_games[channel_id]
        else: # El usuario se equivocó
            await message.channel.send("¡Incorrecto! Intenta adivinar una letra o la palabra completa.")
            game['rounds'] -= 1
            if game['rounds'] > 0:
                await message.channel.send(f"Te quedan {game['rounds']} rondas.")
            else:
                await message.channel.send(f"¡Se acabaron las rondas! La palabra era '{game['word']}'.")
                del word_games[channel_id]


@bot.listen("on_raw_reaction_add")
async def mission_reaction_tracker(payload):
    if payload.member.bot:
        return
    await asyncio.to_thread(db.update_mission_progress, payload.member.id, "reaction_add")

@bot.listen("on_application_command")
async def mission_slash_command_tracker(ctx):
    if ctx.author.bot:
        return
    await asyncio.to_thread(db.update_mission_progress, ctx.author.id, "slash_command_use")

@bot.listen("on_voice_state_update")
async def mission_voice_tracker(member, before, after):
    if member.bot:
        return
    if before.channel is None and after.channel is not None:
        await asyncio.to_thread(db.update_mission_progress, member.id, "voice_minutes", progress_increase=0)
    if before.channel is not None and after.channel is None:
        await asyncio.to_thread(db.update_mission_progress, member.id, "voice_minutes", progress_increase=1)


# --- COMANDOS DE BARRA ---
@bot.slash_command(guild_ids=[GUILD_ID], name="ayuda", description="Muestra el menú principal y la información del bot.")
async def ayuda(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(
        title="📚 𝑮𝒖𝒊́𝒂 𝒅𝒆 𝒄𝒐𝒎𝒂𝒏𝒅𝐨s",
        description="Aquí tienes todos los comandos disponibles para participar en el evento.",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(name="☀️ `/login_diario`", value="Reclama 5 LBucks cada 24 horas. ¡Es la forma más fácil de ganar!", inline=False)
    embed.add_field(name="🏪 `/canjear`", value="Abre el Centro de Canjeo para intercambiar tus LBucks por Robux y otros premios.", inline=False)
    embed.add_field(name="💵 `/saldo`", value="Consulta tu saldo de LBucks en cualquier momento.", inline=False)
    embed.add_field(name="🎁 `/donar`", value="Dona LBucks a otro usuario del servidor.", inline=False)
    embed.add_field(name="📝 `/misiones`", value="Consulta tus misiones diarias y el progreso para ganar recompensas adicionales.", inline=False)
    embed.add_field(name="🕹️ `/adivinar_numero`", value="Inicia un juego para adivinar un número aleatorio y ganar LBucks.", inline=False)
    embed.add_field(name="📚 `/adivinar_palabra`", value="Inicia una partida para adivinar una palabra aleatoria.", inline=False)
    embed.add_field(name="👤 `/invitaciones`", value="Revisa la cantidad de personas que has invitado y tu recompensa.", inline=False)
    embed.add_field(
        name="➕ Robux Pendientes",
        value="""Para ver tus Robux pendientes de canje, ve a la página web de Roblox, haz clic en el ícono de Robux y luego en **"Mis transacciones"**. Los Robux pendientes estarán visibles en el apartado de **"Robux pendientes"** .""",
        inline=False
    )
    embed.set_footer(text="¡Gracias por participar en nuestro evento! 🎉")
    await ctx.followup.send(embed=embed, ephemeral=True)


@bot.slash_command(guild_ids=[GUILD_ID], name="login_diario", description="Reclama tu recompensa diaria de 5 LBucks.")
async def daily_command(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    try:
        user_id = ctx.user.id
        user_data = await asyncio.to_thread(db.get_user, user_id)
        if user_data is None:
            await ctx.followup.send("Error al obtener tus datos. Intenta de nuevo.", ephemeral=True)
            return
        last_claim_time = user_data[2]
        if isinstance(last_claim_time, str):
            try:
                last_claim_time = datetime.datetime.fromisoformat(last_claim_time).replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                last_claim_time = None
        if isinstance(last_claim_time, datetime.datetime) and (datetime.datetime.now(datetime.UTC) - last_claim_time < datetime.timedelta(hours=24)):
            time_left = datetime.timedelta(hours=24) - (datetime.datetime.now(datetime.UTC) - last_claim_time)
            hours, rem = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
            await ctx.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.", ephemeral=True)
            return
        await asyncio.to_thread(db.update_lbucks, user_id, 5)
        await asyncio.to_thread(db.update_daily_claim, user_id)
        await ctx.followup.send("¡Has recibido 5 LBucks! 🪙", ephemeral=True)
    except Exception as e:
        print(f"🚨 Error inesperado en daily_command: {e}")
        await ctx.followup.send("Ocurrió un error al procesar tu recompensa. Intenta de nuevo más tarde.", ephemeral=True)


@bot.slash_command(guild_ids=[GUILD_ID], name="canjear", description="Abre el centro de canjeo para canjear LBucks por Robux.")
async def canjear(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    items = await asyncio.to_thread(db.get_shop_items) or []
    await ctx.followup.send("Abriendo el Centro de Canjeo...", view=RedeemMenuView(items), ephemeral=True)


@bot.slash_command(guild_ids=[GUILD_ID], name="saldo", description="Consulta tu saldo actual de LBucks.")
async def saldo(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    balance = await asyncio.to_thread(db.get_balance, ctx.user.id)
    await ctx.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙", view=UpdateBalanceView(), ephemeral=True)


@bot.slash_command(guild_ids=[GUILD_ID], name="donar", description="Dona LBucks a otro usuario.")
async def donar(ctx: discord.ApplicationContext):
    modal = DonateModal()
    await ctx.response.send_modal(modal)


@bot.slash_command(guild_ids=[GUILD_ID], name="misiones", description="Muestra tus misiones diarias.")
async def misiones(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    missions = await asyncio.to_thread(db.get_daily_missions, ctx.user.id)
    if not missions:
        await ctx.followup.send("No hay misiones disponibles en este momento. Inténtalo más tarde.", ephemeral=True)
        return
    embed = discord.Embed(title="📝 Tus Misiones Diarias", description="Completa estas misiones para ganar LBucks.", color=discord.Color.blue())
    for m in missions:
        status_emoji = "✅" if m['is_completed'] else "⌛"
        progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
        embed.add_field(name=f"{status_emoji} {m['description']}", value=f"Recompensa: **{m['reward']} LBucks** {progress_text}", inline=False)
    await ctx.followup.send(embed=embed, view=UpdateMissionsView(), ephemeral=True)


@bot.slash_command(guild_ids=[GUILD_ID], name="adivinar_numero", description="Inicia un juego para adivinar un número aleatorio y gana LBucks.")
async def guess_number_game(ctx: discord.ApplicationContext, guess: int=None):
    await ctx.defer(ephemeral=False)
    user_id = ctx.user.id
    channel_id = ctx.channel.id
    
    if guess is None:
        if channel_id in number_games:
            await ctx.followup.send("¡Ya hay un juego en curso en este canal! Adivina con el mismo comando.", ephemeral=False)
            return
        
        number_games[channel_id] = {
            'number': random.randint(1, 100), 
            'guesses': {}, 
            'start_time': datetime.datetime.now(),
            'started_by': user_id
        }
        
        admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
        if admin_role and admin_role in ctx.user.roles:
            pista = f"He pensado en un número entre 1 y 100. El número es **{number_games[channel_id]['number']}**. Tienes 1 minuto para adivinarlo."
        else:
            pista_par_impar = "par" if number_games[channel_id]['number'] % 2 == 0 else "impar"
            pista = f"¡He pensado en un número entre 1 y 100! Tienes 1 minuto para adivinarlo. La pista: Es un número **{pista_par_impar}**. 😉"
        await ctx.followup.send(pista, ephemeral=False)
        return

    # Lógica de adivinanza
    if channel_id not in number_games:
        await ctx.followup.send("No hay un juego en curso en este canal. Usa `/adivinar_numero` para empezar uno.", ephemeral=False)
        return
        
    game = number_games[channel_id]
    
    if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=1):
        await ctx.followup.send(f"¡Se acabó el tiempo! El número era {game['number']}. Intenta de nuevo con `/adivinar_numero`.", ephemeral=False)
        del number_games[channel_id]
        return
    
    game['guesses'][user_id] = game['guesses'].get(user_id, 0) + 1
    
    if guess == game['number']:
        reward = 8
        await asyncio.to_thread(db.update_lbucks, user_id, reward)
        await ctx.followup.send(f"¡Felicidades, {ctx.user.mention}! Adivinaste el número {game['number']} en {game['guesses'][user_id]} intentos. Has ganado **{reward} LBucks**. 🥳", ephemeral=False)
        del number_games[channel_id]
    elif guess < game['number']:
        await ctx.followup.send(f"Mi número es mayor. Inténtalo de nuevo.", ephemeral=False)
    else:
        await ctx.followup.send(f"Mi número es menor. Inténtalo de nuevo.", ephemeral=False)


@bot.slash_command(guild_ids=[GUILD_ID], name="adivinar_palabra", description="Inicia una partida para adivinar una palabra oculta.")
async def guess_word_game(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=False)
    channel_id = ctx.channel.id
    if channel_id in word_games:
        await ctx.followup.send("¡Ya hay una partida en curso en este canal! Intenta adivinar la palabra.", ephemeral=False)
        return
    word_to_guess = await get_random_word_from_api()
    if not word_to_guess:
        await ctx.followup.send("No se pudo obtener una palabra. Inténtalo de nuevo más tarde.", ephemeral=False)
        return

    word_games[channel_id] = {'word': word_to_guess, 'guessed_letters': set(), 'start_time': datetime.datetime.now(), 'rounds': 10, 'started_by': ctx.user.id, 'channel_id': ctx.channel.id}
    hint = "".join([c if c in word_games[channel_id]['guessed_letters'] else "_" for c in word_to_guess])
    await ctx.followup.send(f"¡Partida iniciada por {ctx.user.mention}! Tienen 7 minutos y 10 rondas para adivinar la palabra. Pista: `{hint}`", ephemeral=False)


@bot.listen("on_message")
async def guess_word_listener(message):
    if message.author.bot:
        return
    channel_id = message.channel.id
    if channel_id in word_games:
        game = word_games[channel_id]
        user_id = message.author.id

        if datetime.datetime.now() - game['start_time'] > datetime.timedelta(minutes=7):
            await message.channel.send(f"¡Se acabó el tiempo o las rondas para el juego de adivinar palabras de {message.author.mention}! La palabra era '{game['word']}'.")
            del word_games[channel_id]
            return
        
        guess = message.content.lower()

        if len(guess) == 1 and guess.isalpha(): # El usuario adivinó una letra
            if guess in game['guessed_letters']:
                await message.channel.send("¡Ya adivinaste esa letra! Intenta con otra.")
                return
            
            game['guessed_letters'].add(guess)
            new_hint = "".join([c if c in game['guessed_letters'] else "_" for c in game['word']])
            
            if guess in game['word']:
                if "_" not in new_hint:
                    reward = 20
                    await asyncio.to_thread(db.update_lbucks, user_id, reward)
                    await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra '{game['word']}' y has ganado **{reward} LBucks**. 🥳")
                    del word_games[channel_id]
                else:
                    await message.channel.send(f"¡Bien hecho, {message.author.mention}! La palabra es: `{new_hint}`")
            else:
                await message.channel.send(f"¡Incorrecto, {message.author.mention}! La letra '{guess}' no está en la palabra. La palabra es: `{new_hint}`")
                game['rounds'] -= 1
                if game['rounds'] > 0:
                    await message.channel.send(f"Te quedan {game['rounds']} rondas.")
                else:
                    await message.channel.send(f"¡Se acabaron las rondas! La palabra era '{game['word']}'.")
                    del word_games[channel_id]

        elif guess == game['word']: # El usuario adivinó la palabra completa
            reward = 20
            await asyncio.to_thread(db.update_lbucks, user_id, reward)
            await message.channel.send(f"¡Felicidades, {message.author.mention}! Adivinaste la palabra '{game['word']}' y has ganado **{reward} LBucks**. 🥳")
            del word_games[channel_id]
        else: # El usuario se equivocó
            await message.channel.send("¡Incorrecto! Intenta adivinar una letra o la palabra completa.")
            game['rounds'] -= 1
            if game['rounds'] > 0:
                await message.channel.send(f"Te quedan {game['rounds']} rondas.")
            else:
                await message.channel.send(f"¡Se acabaron las rondas! La palabra era '{game['word']}'.")
                del word_games[channel_id]


# --- SISTEMA DE INVITACIONES ---
@bot.slash_command(guild_ids=[GUILD_ID], name="invitaciones", description="Muestra la cantidad de personas que has invitado al servidor.")
async def show_invites(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    inviter_id = ctx.user.id
    invites_count = await asyncio.to_thread(db.get_invite_count, inviter_id)
    await ctx.followup.send(f"Has invitado a **{invites_count}** personas al servidor. ¡Sigue así! 🚀", ephemeral=True)

# --- COMANDOS DE ADMINISTRACIÓN ---
admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])
@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
@discord.default_permissions(administrator=True)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role is None or admin_role not in ctx.author.roles:
        return await ctx.respond("No tienes el rol de administrador para usar este comando.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    await asyncio.to_thread(db.update_lbucks, usuario.id, cantidad)
    await ctx.followup.send(f"Se han añadido {cantidad} LBucks a {usuario.mention}.", ephemeral=True)


# --- SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    serve(app, host="0.0.0.0", port=8080)

def run_bot():
    bot.run(TOKEN)

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    bot.loop.create_task(check_word_game_timeout())
    run_bot()
