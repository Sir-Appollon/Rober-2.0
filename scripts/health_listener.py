import subprocess
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    pass  # no output

@bot.command(name="health")
async def run_health(ctx):
    if ctx.channel.id != CHANNEL_ID:
        return

    await ctx.send("Running health check...")
    try:
        subprocess.run(["python3", "/app/Health.py"], timeout=60)
        await ctx.send("Health check executed.")
    except Exception as e:
        await ctx.send(f"Execution failed: {e}")

bot.run(TOKEN)
