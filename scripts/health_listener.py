import discord
import subprocess
import os
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    print(f"[DEBUG] Logged in as {bot.user}")

@bot.command(name="health")
async def run_health(ctx):
    if ctx.channel.id != CHANNEL_ID:
        return
    await ctx.send("Running health check...")

    try:
        result = subprocess.run(
            ["python3", "/app/Health.py"],
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout or "[no output]"
        await ctx.send(f"```{output[:1900]}```")
    except Exception as e:
        await ctx.send(f"Health check failed: {e}")

bot.run(TOKEN)
