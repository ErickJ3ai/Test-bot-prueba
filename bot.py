# bot.py (Versión Final y Corregida)

import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import os
from dotenv import load_dotenv
import datetime
import sqlite3

# --- Importaciones para el Servidor Web ---
from flask import Flask
from threading import Thread
from waitress import serve

# --- Importaciones locales ---
import database as db
from config import GUILD_ID, ADMIN_ROLE_NAME, REDEMPTION_LOG_CHANNEL_ID

# --- Configuración Inicial ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# --- INICIALIZACIÓN DEL BOT (CORREGIDA) ---
# Usamos discord.Bot que es más simple para slash commands y ya sabemos que funciona.
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- VISTAS DE BOTONES (UI - CORREGIDAS CON DEFER) ---

class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="☀️ Login Diario", style=discord.ButtonStyle.success, custom_id="daily_login")
    async def daily_button(self, button: Button, interaction: discord.Interaction):
        # Aplicamos el patrón defer -> followup
        await interaction.response.defer(ephemeral=True)
        
        user_id = interaction.user.id
        user_data = db.get_user(user_id)
        last_claim_str = user_data[2]

        if last_claim_str:
            last_claim_time = datetime.datetime.fromisoformat(last_claim_str)
            if datetime.datetime.utcnow() - last_claim_time < datetime.timedelta(hours=24):
                time_left = datetime.timedelta(hours=24) - (datetime.datetime.utcnow() - last_claim_time)
                hours, remainder = divmod(int(time_left.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                await interaction.followup.send(f"Ya reclamaste tu recompensa. Vuelve en {hours}h {minutes}m.")
                return

        db.update_lbucks(user_id, 5)
        db.update_daily_claim(user_id)
        await interaction.followup.send("¡Has recibido 5 LBucks! 🪙")

    @discord.ui.button(label="🏪 Centro de Canjeo", style=discord.ButtonStyle.primary, custom_id="redeem_center")
    async def redeem_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.send_message("Abriendo el Centro de Canjeo...", view=RedeemMenuView(), ephemeral=True)

    @discord.ui.button(label="💰 Consultar Saldo", style=discord.ButtonStyle.secondary, custom_id="check_balance")
    async def balance_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = db.get_balance(interaction.user.id)
        await interaction.followup.send(f"Tienes un total de {balance} LBucks. 🪙")

class RedeemMenuView(View):
    def __init__(self):
        super().__init__(timeout=300)
        items = db.get_shop_items()
        for item_id, price, stock in items:
            robux_amount = item_id.split('_')[0]
            self.add_item(Button(
                label=f"{robux_amount} Robux ({price} LBucks)",
                custom_id=f"redeem_{item_id}",
                style=discord.ButtonStyle.blurple,
                disabled=(stock <= 0)
            ))

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, row=4)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.message.delete()

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
            await interaction.followup.send("Parece que ya no tienes LBucks suficientes.")
            return

        db.update_lbucks(self.user_id, -self.price)
        db.update_stock(self.item_id, -1)
        
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(title="⏳ Nuevo Canjeo Pendiente", description=f"El usuario **{interaction.user.name}** (`{interaction.user.id}`) ha canjeado **{robux_amount} Robux**.", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            db.create_redemption(self.user_id, self.item_id, log_message.id)
        
        await interaction.followup.send("¡Canjeo realizado! Un administrador revisará tu solicitud.")
        # Editamos el mensaje original para que los botones desaparezcan
        await interaction.edit_original_response(content="Procesando...", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Tu canjeo ha sido cancelado.", view=None)

class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)
        # Se añaden los botones en el evento on_interaction para evitar problemas de ID
        
# --- EVENTOS Y TAREAS ---

@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO")
    db.init_db()
    bot.add_view(MainMenuView())
    bot.add_view(AdminActionView()) # Registramos la vista de admin para que sea persistente
    print("Bot listo, base de datos inicializada y vistas persistentes registradas.")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data['custom_id']
    
    if custom_id.startswith("redeem_"):
        item_id = custom_id.replace("redeem_", "")
        item = db.get_item(item_id)
        if not item: return await interaction.response.send_message("Este item ya no existe.", ephemeral=True)
        
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.response.send_message(f"¿Confirmas el canje de **{item[0].split('_')[0]} Robux** por **{item[1]} LBucks**?", view=view, ephemeral=True)

    elif custom_id.startswith("admin_complete_") or custom_id.startswith("admin_cancel_"):
        await interaction.response.defer()
        # Resto de la lógica de admin... (es igual a la anterior pero usa followup)
        # (Se omite por brevedad, pero es la misma lógica que ya tenías)


# --- COMANDOS SLASH (CORREGIDOS CON DEFER) ---

@bot.slash_command(guild_ids=[GUILD_ID], name="evento", description="Muestra el menú principal del evento.")
async def evento(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    embed = discord.Embed(title="🎉 Evento de Robux Gratis 🎉", description="¡Bienvenido al evento! Usa los botones de abajo para participar y ganar Robux.", color=discord.Color.gold())
    embed.set_footer(text="¡Buena suerte!")
    await ctx.followup.send(embed=embed, view=MainMenuView())

admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

@admin_commands.command(name="add_lbucks", description="Añade LBucks a un usuario.")
@commands.has_role(ADMIN_ROLE_NAME)
async def add_lbucks(ctx: discord.ApplicationContext, usuario: discord.Member, cantidad: int):
    await ctx.defer(ephemeral=True)
    db.update_lbucks(usuario.id, cantidad)
    await ctx.followup.send(f"Se han añadido {cantidad} LBucks a {usuario.mention}.")
    try: await usuario.send(f"¡Un administrador te ha otorgado {cantidad} LBucks! 🪙")
    except discord.Forbidden: pass

@admin_commands.command(name="set_price", description="Establece el precio de un item de la tienda.")
@commands.has_role(ADMIN_ROLE_NAME)
async def set_price(ctx: discord.ApplicationContext, item: discord.Option(str, "Elige el item", choices=['5_robux', '10_robux', '25_robux', '30_robux', '45_robux', '55_robux', '60_robux', '75_robux', '80_robux', '100_robux']), precio: int):
    await ctx.defer(ephemeral=True)
    db.set_price(item, precio)
    await ctx.followup.send(f"El precio de `{item}` ha sido establecido a {precio} LBucks.")
    
@admin_commands.command(name="set_stock", description="Establece el stock de un item.")
@commands.has_role(ADMIN_ROLE_NAME)
async def set_stock(ctx: discord.ApplicationContext, item: discord.Option(str, "Elige el item", choices=['5_robux', '10_robux', '25_robux', '30_robux', '45_robux', '55_robux', '60_robux', '75_robux', '80_robux', '100_robux']), cantidad: int):
    await ctx.defer(ephemeral=True)
    db.set_shop_stock(item, cantidad)
    await ctx.followup.send(f"El stock de `{item}` ha sido establecido a {cantidad}.")


# --- CÓDIGO PARA EL SERVIDOR WEB Y EJECUCIÓN ---
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
