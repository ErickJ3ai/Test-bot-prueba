import discord
from discord.ext import commands
from discord.ui import Button, View
import os
from dotenv import load_dotenv
import datetime
import sqlite3
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

    @discord.ui.button(label="☀️ Login Diario", style=discord.ButtonStyle.success, custom_id="main:daily_login")
    async def daily_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        user_data = db.get_user(user_id)
        if user_data is None:
            await interaction.followup.send("Error al obtener tus datos. Intenta de nuevo.")
            return
        last_claim_str = user_data[2]
        if last_claim_str:
            last_claim_time = datetime.datetime.fromisoformat(last_claim_str)
            if datetime.datetime.utcnow() - last_claim_time < datetime.timedelta(hours=24):
                time_left = datetime.timedelta(hours=24) - (datetime.datetime.utcnow() - last_claim_time)
                hours, rem = divmod(int(time_left.total_seconds()), 3600)
                minutes, _ = divmod(rem, 60)
                await interaction.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.")
                return
        db.update_lbucks(user_id, 5)
        db.update_daily_claim(user_id)
        await interaction.followup.send("¡Has recibido 5 LBucks! 🪙")

    @discord.ui.button(label="🏪 Centro de Canjeo", style=discord.ButtonStyle.primary, custom_id="main:redeem_center")
    async def redeem_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.send_message("Abriendo el Centro de Canjeo...", view=RedeemMenuView(), ephemeral=True)

    @discord.ui.button(label="💰 Consultar Saldo", style=discord.ButtonStyle.secondary, custom_id="main:check_balance")
    async def balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = db.get_balance(interaction.user.id)
        await interaction.followup.send(f"Tienes un total de {balance} LBucks. 🪙")

    # Nuevo botón para ver saldo (con label "💵 Ver saldo")
    @discord.ui.button(label="💵 Ver saldo", style=discord.ButtonStyle.secondary, custom_id="main:view_balance")
    async def view_balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = db.get_balance(interaction.user.id)
        await interaction.followup.send(f"Tu saldo actual es: **{balance} LBucks** 🪙")

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
                description=f"El usuario **{interaction.user.name}** (`{interaction.user.id}`) ha canjeado **{robux_amount} Robux**.",
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
    db.init_db()
    try:
        synced = await bot.sync_commands(guild_id=GUILD_ID)
        print(f"🔄 {len(synced)} comandos sincronizados con el servidor.")
    except Exception as e:
        print(f"⚠️ Error al sincronizar comandos: {e}")

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

# --- COMANDOS SLASH ---
@bot.slash_command(guild_ids=[GUILD_ID], name="evento", description="Muestra el menú principal del evento.")
async def evento(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(title="🎉 Evento de Robux Gratis 🎉", description="¡Bienvenido al evento! Usa los botones de abajo.", color=discord.Color.gold())
    await ctx.followup.send(embed=embed, view=MainMenuView())

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

@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
@discord.default_permissions(administrator=True)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    await ctx.defer(ephemeral=True)
    db.update_lbucks(usuario.id, cantidad)
    await ctx.followup.send(f"Se han añadido {cantidad} LBucks a {usuario.mention}.")

# --- SERVIDOR WEB Y EJECUCIÓN ---
app = Flask('')
@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    serve(app, host="0.0.0.0", port=8080)
    
async def start_bot():
    # Registrar vistas persistentes aquí, cuando el loop ya esté activo
    bot.add_view(MainMenuView())
    bot.add_view(AdminActionView())
    await bot.start(TOKEN)
def run_bot():
    # Registrar vistas persistentes ANTES de ejecutar el bot
    asyncio.run(bot.start(TOKEN))

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    run_bot()
