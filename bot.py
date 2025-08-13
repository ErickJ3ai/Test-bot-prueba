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

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- VISTAS DE BOTONES (UI) ---
class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="☀️ Login Diario", style=discord.ButtonStyle.success, custom_id="main:daily_login")
    async def daily_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = interaction.user.id
            user_data = await asyncio.to_thread(db.get_user, user_id)

            if user_data is None:
                await interaction.followup.send("Error al obtener tus datos. Intenta de nuevo.", ephemeral=True)
                return

            last_claim_time = user_data

            if isinstance(last_claim_time, str):
                try:
                    last_claim_time = datetime.datetime.fromisoformat(last_claim_time).replace(tzinfo=datetime.timezone.utc)
                except ValueError:
                    last_claim_time = None

            if isinstance(last_claim_time, datetime.datetime) and (datetime.datetime.now(datetime.UTC) - last_claim_time < datetime.timedelta(hours=24)):
                time_left = datetime.timedelta(hours=24) - (datetime.datetime.now(datetime.UTC) - last_claim_time)
                hours, rem = divmod(int(time_left.total_seconds()), 3600)
                minutes, _ = divmod(rem, 60)
                await interaction.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.", ephemeral=True)
                return

            await asyncio.to_thread(db.update_lbucks, user_id, 5)
            await asyncio.to_thread(db.update_daily_claim, user_id)
            await interaction.followup.send("¡Has recibido 5 LBucks! 🪙", ephemeral=True)

        except Exception as e:
            print(f"🚨 Error inesperado en daily_button: {e}")
            await interaction.followup.send("Ocurrió un error al procesar tu recompensa. Intenta de nuevo más tarde.", ephemeral=True)

    @discord.ui.button(label="🏪 Centro de Canjeo", style=discord.ButtonStyle.primary, custom_id="main:redeem_center")
    async def redeem_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        items = await asyncio.to_thread(db.get_shop_items) or []
        await interaction.followup.send("Abriendo el Centro de Canjeo...", view=RedeemMenuView(items), ephemeral=True)

    @discord.ui.button(label="💵 Ver saldo", style=discord.ButtonStyle.secondary, custom_id="main:view_balance")
    async def view_balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙", ephemeral=True)

    @discord.ui.button(label="🎁 Donar", style=discord.ButtonStyle.secondary, custom_id="main:donate_lbucks")
    async def donate_button(self, button: Button, interaction: discord.Interaction):
        modal = DonateModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📝 Misiones", style=discord.ButtonStyle.secondary, custom_id="main:missions")
    async def missions_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        missions = await asyncio.to_thread(db.get_daily_missions, interaction.user.id)
        if not missions:
            await interaction.followup.send("No hay misiones disponibles en este momento. Inténtalo más tarde.", ephemeral=True)
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

        await interaction.followup.send(embed=embed, ephemeral=True)

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

            doner_balance = db.get_balance(interaction.user.id)
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
        # Organizar los botones en filas para mejor presentación
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
            # Añadir una fila después de cada 3 botones (ajusta según prefieras)
            # if (i + 1) % 3 == 0 and i < len(self.items) - 1:
            #     self.add_item(discord.ui.Button(label="", disabled=True, style=discord.ButtonStyle.grey)) # Espaciador

    async def handle_redeem_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        custom_id = interaction.data['custom_id']
        item_id = custom_id.replace("redeem_", "")

        item = await asyncio.to_thread(db.get_item, item_id)

        if not item:
            return await interaction.followup.send("Este item ya no existe.", ephemeral=True)

        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item

 [1])
        await interaction.followup.send(
            f"¿Confirmas el canje de **{item}** "
            f"por **{item} LBucks**?",
            view=view,
            ephemeral=True
        )

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

        if not item_data or item_data <= 0:
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
            embed = discord.Embed(
                title="⏳ Nuevo Canjeo Pendiente",
                description=f"El usuario **{interaction.user.name}** ({interaction.user.id}) ha canjeado **{robux_amount} Robux**.",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.utcnow()
            )
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

        redemption = db.get_redemption_by_message(interaction.message.id)
        if not redemption or redemption != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)

        await asyncio.to_thread(db.update_redemption_status, redemption, 'completed')
        user = await bot.fetch_user(redemption)
        item_name = redemption + " Robux"
        try:
            await user.send(f"✅ ¡Tu canjeo de **{item_name}** ha sido completado!")
        except discord.Forbidden:
            pass

        edited_embed = interaction.message.embeds
        edited_embed = "✅ Canjeo Completado"
        edited_embed = discord.Color.green()
        edited_embed = interaction.user.mention
        await interaction.edit_original_response(embed=edited_embed, view=None)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.", ephemeral=True)

        redemption = db.get_redemption_by_message(interaction.message.id)
        if not redemption or redemption != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)

        item = await asyncio.to_thread(db.get_item, redemption)
        if item:
            await asyncio.to_thread(db.update_lbucks, redemption, item)
            await asyncio.to_thread(db.update_stock, redemption, 1)

        await asyncio.to_thread(db.update_redemption_status, redemption, 'cancelled_by_admin')
        user = await bot.fetch_user(redemption)
        item_name = redemption + " Robux"
        try:
            await user.send(f"❌ Tu canjeo de **{item_name}** fue cancelado. Tus LBucks han sido devueltos.")
        except discord.Forbidden:
            pass

        edited_embed = interaction.message.embeds
        edited_embed = "❌ Canjeo Cancelado por Admin"
        edited_embed = discord.Color.dark_grey()
        edited_embed = interaction.user.mention
        await interaction.edit_original_response(embed=edited_embed, view=None)


# --- EVENTOS ---
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
            bot.persistent_views_added = True
            print("👁️ Vistas persistentes registradas.")
    except Exception as e:
        print(f"⚠️ Error al registrar vistas persistentes: {e}")

@bot.listen("on_message")
async def mission_message_tracker(message):
    if message.author.bot:
        return
    await asyncio.to_thread(db.update_mission_progress, message.author.id, "message_count")

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


# -------------------------------------------------------------
#  NUEVOS COMANDOS DE BARRA
# -------------------------------------------------------------
@bot.slash_command(guild_ids=[GUILD_ID], name="ayuda", description="Muestra el menú principal y la información del bot.")
async def ayuda(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(
        title="📚 𝑮𝒖𝒊́𝒂 𝒅𝒆 𝒄𝒐𝒎𝒂𝒏𝒅𝒐𝒔",
        description="Aquí tienes todos los comandos disponibles para participar en el evento.",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(
        name="☀️ `/login_diario`",
        value="Reclama 5 LBucks cada 24 horas. ¡Es la forma más fácil de ganar!",
        inline=False
    )
    embed.add_field(
        name="🏪 `/canjear`",
        value="Abre el Centro de Canjeo para intercambiar tus LBucks por Robux y otros premios.",
        inline=False
    )
    embed.add_field(
        name="💵 `/saldo`",
        value="Consulta tu saldo de LBucks en cualquier momento.",
        inline=False
    )
    embed.add_field(
        name="🎁 `/donar`",
        value="Dona LBucks a otro usuario del servidor.",
        inline=False
    )
    embed.add_field(
        name="📝 `/misiones`",
        value="Consulta tus misiones diarias y el progreso para ganar recompensas adicionales.",
        inline=False
    )
    embed.add_field(
        name="➕ Robux Pendientes",
        value="""Para ver tus Robux pendientes de canje, ve a la página web de Roblox, haz clic en el ícono de Robux  y luego en **"Mis transacciones"** . Los Robux pendientes estarán visibles en el apartado de **"Robux pendientes"** .""",
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

        last_claim_time = user_data

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
    await ctx.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙", ephemeral=True)

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

    await ctx.followup.send(embed=embed, ephemeral=True)

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
    run_bot()
