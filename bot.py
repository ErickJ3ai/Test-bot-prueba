import discord
from discord.ext import commands # Necesitamos esto para has_role
import os
from config import GUILD_ID, ADMIN_ROLE_NAME # Importamos desde config
import database as db

TOKEN = os.getenv('DISCORD_TOKEN')

# Usamos discord.Bot que es más simple y ya sabemos que funciona
intents = discord.Intents.default()
bot = discord.Bot(intents=intents)

@bot.event
async def on_ready():
    print(f"✅ BOT '{bot.user}' CONECTADO")
    db.init_db() # Esta línea es la que ejecuta la creación de las tablas

@bot.slash_command(guild_ids=[GUILD_ID], name="hola", description="Un comando de prueba.")
async def hola(ctx: discord.ApplicationContext):
    print(f"✅--- Comando /hola recibido")
    await ctx.respond("¡Hola! La base del bot funciona.")

# Añadimos el grupo de comandos de admin
admin_commands = bot.create_group("admin", "Comandos de administración", guild_ids=[GUILD_ID])

@admin_commands.command(name="ping", description="Prueba si los comandos de admin funcionan.")
@commands.has_role(ADMIN_ROLE_NAME) # Verificamos si la lectura de rol funciona
async def ping_admin(ctx: discord.ApplicationContext):
    await ctx.respond("Pong! Los comandos de admin están funcionando.", ephemeral=True)
# Añade este comando dentro de la sección de admin
@admin_commands.command(name="test_db", description="Prueba la conexión con la base de datos.")
@commands.has_role(ADMIN_ROLE_NAME)
async def test_db(ctx: discord.ApplicationContext):
    try:
        balance = db.get_balance(ctx.author.id)
        await ctx.respond(f"Conexión con la DB exitosa. Tu saldo es: {balance} LBucks.", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"Error al conectar con la DB: {e}", ephemeral=True)

bot.run(TOKEN)
