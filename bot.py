import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ButtonStyle
from discord.ui import View, Button
from dotenv import load_dotenv
from threading import Thread
from flask import Flask
from waitress import serve
from database import db
from views.admin import AdminActionView
from database.db import get_balance

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = discord.Object(id=int(os.getenv("DISCORD_GUILD_ID")))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- VISTAS ---

class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📜 Misiones", style=ButtonStyle.primary, custom_id="missions_button")
    async def missions_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("📜 Aún no hay misiones disponibles.", ephemeral=True)

    @discord.ui.button(label="💵 Ver saldo", style=ButtonStyle.success, custom_id="balance_button")
    async def balance_button(self, interaction: Interaction, button: Button):
        user_id = interaction.user.id
        balance = get_balance(user_id)
        await interaction.response.send_message(
            f"💸 Tu saldo actual es de **{balance} LBucks**.", ephemeral=True
        )

    @discord.ui.button(label="🎁 Canjear", style=ButtonStyle.secondary, custom_id="redeem_button")
    async def redeem_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("🎁 El canje está en construcción.", ephemeral=True)

    @discord.ui.button(label="❌ Cancelar canjeo", style=ButtonStyle.danger, custom_id="cancel_redeem_button")
    async def cancel_redeem_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("❌ No tienes canjeos pendientes.", ephemeral=True)

# --- COMANDOS SLASH ---
@bot.tree.command(name="menu", description="📋 Mostrar menú principal")
async def menu(interaction: Interaction):
    await interaction.response.send_message(
        "📋 Este es tu menú principal. Elige una opción:",
        view=MainMenuView(),
        ephemeral=True
    )

@bot.tree.command(name="saldo", description="💰 Ver tu saldo actual de LBucks")
async def saldo(interaction: Interaction):
    user_id = interaction.user.id
    balance = get_balance(user_id)
    await interaction.response.send_message(
        f"💸 Tu saldo actual es de **{balance} LBucks**.", ephemeral=True
    )

# --- EVENTOS ---
@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO Y LISTO")

    db.init_db()

    try:
        synced = await bot.tree.sync(guild=GUILD_ID)
        print(f"🔄 {len(synced)} comandos sincronizados con el servidor.")
    except Exception as e:
        print(f"⚠️ Error al sincronizar comandos: {e}")

    # Registrar vistas persistentes
    bot.add_view(MainMenuView())
    bot.add_view(AdminActionView())

# --- FLASK KEEP-ALIVE ---
app = Flask('')

@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
    serve(app, host="0.0.0.0", port=8080)

# --- EJECUCIÓN ---
def run_bot():
    bot.run(TOKEN)

if __name__ == "__main__":
    web_server_thread = Thread(target=run_web_server)
    web_server_thread.start()
    run_bot()
