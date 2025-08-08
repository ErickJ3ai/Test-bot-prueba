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
TOKEN = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- VISTAS DE BOTONES (UI) ---

class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

   # Código corregido para la función daily_button
@discord.ui.button(label="☀️ Login Diario", style=discord.ButtonStyle.success, custom_id="main:daily_login")
async def daily_button(self, button: Button, interaction: discord.Interaction):
        # La respuesta inicial se envía aquí.
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        user_data = db.get_user(user_id)
        
        if user_data is None:
            await interaction.followup.send("Error al obtener tus datos. Intenta de nuevo.")
            return

        last_claim_time = user_data[2]
        
        # Lógica para manejar el formato de fecha
        if isinstance(last_claim_time, str):
            try:
                last_claim_time = datetime.datetime.fromisoformat(last_claim_time)
            except ValueError:
                last_claim_time = None

        # Verificar si ya reclamó en las últimas 24h
        if isinstance(last_claim_time, datetime.datetime) and (datetime.datetime.utcnow() - last_claim_time < datetime.timedelta(hours=24)):
            time_left = datetime.timedelta(hours=24) - (datetime.datetime.utcnow() - last_claim_time)
            hours, rem = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
            await interaction.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.")
            return

        # Si todo es correcto, dar la recompensa
        try:
            db.claim_daily_reward(user_id, 5)
            await interaction.followup.send("¡Has recibido 5 LBucks! 🪙")
        except Exception as e:
            print(f"Error en daily_button: {e}")
            await interaction.followup.send("Ocurrió un error al procesar tu recompensa. Intenta de nuevo más tarde.")
            await interaction.edit_original_response(view=bot.main_menu_view)


    # Código corregido para la función redeem_button
@discord.ui.button(label="🏪 Centro de Canjeo", style=discord.ButtonStyle.primary, custom_id="main:redeem_center")
async def redeem_button(self, button: Button, interaction: discord.Interaction):
    await interaction.response.send_message("Abriendo el Centro de Canjeo...", view=RedeemMenuView(), ephemeral=True)

    @discord.ui.button(label="💵 𝐕𝐞𝐫 𝐬𝐚𝐥𝐝𝐨", style=discord.ButtonStyle.secondary, custom_id="main:view_balance")
    async def view_balance_button(self, button: Button, interaction: discord.Interaction):
        # Esta lógica se ejecuta sin un defer.
        balance = db.get_balance(interaction.user.id)
        await interaction.response.send_message(f"Tu saldo actual es: **{balance} LBucks** 🪙", ephemeral=True)
    
    @discord.ui.button(label="🎁 𝐃𝐨𝐧𝐚𝐫", style=discord.ButtonStyle.secondary, custom_id="main:donate_lbucks")
    async def donate_button(self, button: Button, interaction: discord.Interaction):
        modal = DonateModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📝 Misiones", style=discord.ButtonStyle.secondary, custom_id="main:missions")
    async def missions_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        missions = db.get_daily_missions(interaction.user.id)
        if not missions:
            await interaction.followup.send("No hay misiones disponibles en este momento. Inténtalo más tarde.")
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
            
            await interaction.followup.send(embed=embed)

# Fuera de las clases View, añade esta nueva clase
class DonateModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, title="Donar LBucks")
        
        # Define los campos de texto dentro del constructor
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
        
        # Agrega los campos al modal
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
                await interaction.followup.send("No se pudo encontrar al destinatario.")
                return

            if amount <= 0:
                await interaction.followup.send("La cantidad a donar debe ser un número positivo.")
                return
            
            if interaction.user.id == recipient.id:
                await interaction.followup.send("No puedes donarte LBucks a ti mismo.")
                return

            doner_balance = db.get_balance(interaction.user.id)
            if doner_balance < amount:
                await interaction.followup.send("No tienes suficientes LBucks para donar.")
                return
            
            db.update_lbucks(interaction.user.id, -amount)
            db.update_lbucks(recipient.id, amount)
            
            await interaction.followup.send(f"Has donado **{amount} LBucks** a **{recipient.name}**. ¡Gracias por tu generosidad! 🎉")

        except ValueError:
            await interaction.followup.send("La cantidad debe ser un número válido.")
        except Exception as e:
            print(f"Error en el modal de donación: {e}")
            await interaction.followup.send("Ocurrió un error al procesar tu donación. Intenta de nuevo más tarde.")
            
class RedeemMenuView(View):
    def __init__(self):
        super().__init__(timeout=300)
        items = db.get_shop_items() or []
        for item_id, price, stock in items:
            robux_amount = item_id.split('_')[0]
            self.add_item(Button(
                label=f"{robux_amount} Robux ({price} LBucks)",
                custom_id=f"redeem_{item_id}",
                style=discord.ButtonStyle.blurple,
                disabled=(stock <= 0)
            ))

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar Canjeo", style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = db.get_balance(self.user_id)
        item_data = db.get_item(self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Justo se agotó! Alguien más fue más rápido.")
            return
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.")
            return

        db.update_lbucks(self.user_id, -self.price)
        db.update_stock(self.item_id, -1)
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
            db.create_redemption(self.user_id, self.item_id, log_message.id)
        
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
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)

        db.update_redemption_status(redemption[0], 'completed')
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

        redemption = db.get_redemption_by_message(interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)

        item = db.get_item(redemption[2])
        if item:
            db.update_lbucks(redemption[1], item[1])
            db.update_stock(redemption[2], 1)
        
        db.update_redemption_status(redemption[0], 'cancelled_by_admin')
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


# --- EVENTOS ---
@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")
    
    # ... (El resto del código de on_ready) ...
    
    # Creamos una única instancia de la vista
    bot.main_menu_view = MainMenuView()
    
    # Registramos la vista para que el bot la reconozca después de reinicios
    if not hasattr(bot, "persistent_views_added"):
        bot.add_view(bot.main_menu_view)
        bot.add_view(AdminActionView())
        bot.persistent_views_added = True
        print("👁️ Vistas persistentes registradas.")
    except Exception as e:
        print(f"⚠️ Error al registrar vistas persistentes: {e}")

    try:
        synced = await bot.tree.sync(guild=Object(id=GUILD_ID))
        print(f"🔄 {len(synced)} comandos sincronizados con el servidor.")
    except Exception as e:
        print(f"⚠️ Error al sincronizar comandos: {e}")

# ... (el resto de tu código)
# --- MANEJADOR DE COMPONENTES CON CUSTOM_ID ---
@bot.listen()
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data['custom_id']
        if custom_id.startswith("redeem_"):
            item_id = custom_id.replace("redeem_", "")
            item = db.get_item(item_id)
            if not item:
                return await interaction.response.send_message("Este item ya no existe.", ephemeral=True)
            view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
            await interaction.response.send_message(
                f"¿Confirmas el canje de **{item[0].split('_')[0]} Robux** por **{item[1]} LBucks**?",
                view=view,
                ephemeral=True
            )
            
            # Después de tu manejador de on_interaction
@bot.listen("on_message")
async def mission_message_tracker(message):
    if message.author.bot:
        return
    db.update_mission_progress(message.author.id, "message_count")

@bot.listen("on_raw_reaction_add")
async def mission_reaction_tracker(payload):
    if payload.member.bot:
        return
    db.update_mission_progress(payload.member.id, "reaction_add")


@bot.listen("on_application_command")
async def mission_slash_command_tracker(ctx):
    if ctx.author.bot:
        return
    db.update_mission_progress(ctx.author.id, "slash_command_use")

# Después del nuevo listener de slash commands
@bot.listen("on_voice_state_update")
async def mission_voice_tracker(member, before, after):
    if member.bot:
        return
    
    # Si el usuario se une a un canal de voz
    if before.channel is None and after.channel is not None:
        db.update_mission_progress(member.id, "voice_minutes", progress_increase=0) # Para inicializar
        
    # Si el usuario se desconecta del canal de voz
    if before.channel is not None and after.channel is None:
        # Aquí iría una lógica más compleja para calcular el tiempo
        # Pero para una misión simple, podemos asumir el progreso
        db.update_mission_progress(member.id, "voice_minutes", progress_increase=1)

# Código corregido para la función evento
@bot.slash_command(guild_ids=[GUILD_ID], name="evento", description="Muestra el menú principal del evento.")
async def evento(ctx: discord.ApplicationContext):
    # La respuesta inicial ya no se hace con defer.
    # Se crea el embed y la vista primero.
    embed = discord.Embed(
        title="🎉 ¡𝑩𝒊𝒆𝒏𝒗𝒆𝒏𝒊𝒅𝒐 𝒂𝒍 𝑬𝒗𝒆𝒏𝒕𝒐 𝒅𝒆 𝑹𝒐𝒃𝒖𝒙 𝑷𝒓𝒐𝒑𝒐𝒓𝒄𝒊𝒐𝒏𝒂𝒅𝒐 𝒑𝒐𝒓 𝑳𝒆𝒈𝒆𝒏𝒅𝒔 𝑨𝒄𝒄𝒐𝒖𝒏𝒕! 🎉",
        description="𝑷𝒂𝒓𝒕𝒊𝒄𝒊𝒑𝒂 𝒑𝒂𝒓𝒂 𝒈𝒂𝒏𝒂𝒓 𝑹𝒐𝒃𝒖𝒙 𝒈𝒓𝒂𝒕𝒊𝒔! 𝑼𝒔𝒂 𝒍𝒐𝒔 𝒃𝒐𝒕𝒐𝒏𝒆𝒔 𝒅𝒆 𝒂𝒃𝒂𝒋𝒐 𝒑𝒂𝒓𝒂 𝒊𝒏𝒕𝒆𝒓𝒂𝒄𝒕𝒖𝒂𝒓 𝒚 𝒄𝒐𝒎𝒆𝒏𝒛𝒂𝒓 𝒕𝒖 𝒂𝒗𝒆𝒏𝒕𝒖𝒓𝒂. ¡𝑴𝒖𝒄𝒉𝒂 𝒔𝒖𝒆𝒓𝒕𝒆!",
        color=discord.Color.gold()
    )
    
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    
    embed.add_field(
        name="☀️ Login Diario",
        value="Reclama 5 LBucks cada 24 horas. ¡Es la forma más fácil de ganar!",
        inline=False
    )
    embed.add_field(
        name="🏪 Centro de Canjeo",
        value="Canjea tus LBucks por Robux y otros premios en la tienda.",
        inline=False
    )
    embed.add_field(
        name="💵 Ver saldo",
        value="Consulta tu saldo de LBucks en cualquier momento para saber cuánto tienes.",
        inline=False
    )
    embed.add_field(
        name="🎁 Donar",
        value="Comparte tu riqueza. Dona LBucks a otros usuarios del servidor.",
        inline=False
    )
    embed.add_field(
        name="📝 Misiones",
        value="Completa misiones diarias para ganar recompensas adicionales.",
        inline=False
    )

    embed.set_footer(text="¡Gracias por participar en nuestro evento!")
    
    # La respuesta se envía de forma única y segura con ctx.respond().
    await ctx.respond(embed=embed, view=bot.main_menu_view, ephemeral=True)

# Nuevo comando para consultar saldo
@bot.slash_command(guild_ids=[GUILD_ID], name="saldo", description="Consulta tu saldo actual de LBucks.")
async def saldo(ctx: discord.ApplicationContext):
    balance = db.get_balance(ctx.user.id)
    embed = discord.Embed(
        title="💰 Tu saldo actual",
        description=f"Tienes **{balance} LBucks** disponibles.",
        color=discord.Color.blue()
    )
    class RefreshBalanceView(View):
        @discord.ui.button(label="Actualizar saldo", style=discord.ButtonStyle.secondary)
        async def refresh(self, button: Button, interaction: discord.Interaction):
            new_balance = db.get_balance(interaction.user.id)
            new_embed = discord.Embed(
                title="💰 Tu saldo actual",
                description=f"Tienes **{new_balance} LBucks** disponibles.",
                color=discord.Color.blue()
            )
            await interaction.response.edit_message(embed=new_embed)
    await ctx.respond(embed=embed, view=RefreshBalanceView(), ephemeral=True)

admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

# Código corregido para la función add_lbucks
@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
@discord.default_permissions(administrator=True)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    # Obtener el rol de administrador del servidor
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    
    # Si el rol no existe o el usuario no lo tiene, denegar el permiso
    if admin_role is None or admin_role not in ctx.author.roles:
        return await ctx.respond("No tienes el rol de administrador para usar este comando.", ephemeral=True)
    
    await ctx.defer(ephemeral=True)
    
    # ... El resto de tu lógica ...
    db.update_lbucks(usuario.id, cantidad)
    await ctx.followup.send(f"Se han añadido {cantidad} LBucks a {usuario.mention}.", ephemeral=True)

# --- SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    serve(app, host="0.0.0.0", port=8080)

def run_bot():
   # Registrar vistas persistentes justo antes de iniciar el bot
    bot.run(TOKEN)
if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    run_bot()

