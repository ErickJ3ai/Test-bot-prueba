# test_bot.py
import discord
import os

# --- CONFIGURACIÓN ---
# Lee las variables directamente del entorno de Render.
# Asegúrate de que estas variables están configuradas en tu dashboard de Render.
try:
    TOKEN = os.getenv('DISCORD_TOKEN')
    GUILD_ID = int(os.getenv('GUILD_ID'))
except (TypeError, ValueError):
    print("!!! ERROR: Asegúrate de que las variables de entorno DISCORD_TOKEN y GUILD_ID están configuradas correctamente en Render.")
    exit()

# --- INICIALIZACIÓN DEL BOT ---
bot = discord.Bot()

# --- EVENTOS ---
@bot.event
async def on_ready():
    print("==============================================")
    print(f"✅ BOT DE PRUEBA '{bot.user}' CONECTADO")
    print(f"✅ Registrado para el Guild ID: {GUILD_ID}")
    print("==============================================")

# --- COMANDOS ---
@bot.slash_command(
    guild_ids=[GUILD_ID],
    name="hola",
    description="Un comando de prueba para verificar la funcionalidad básica."
)
async def hola(ctx: discord.ApplicationContext):
    # Este print es la prueba definitiva. Si aparece, el enrutamiento de comandos funciona.
    print(f"✅--- Comando /hola recibido de {ctx.author.name} ---")
    await ctx.respond("¡Hola! La interacción funciona correctamente. 🎉")

# --- EJECUCIÓN ---
print("--- Iniciando bot de prueba... ---")
bot.run(TOKEN)
