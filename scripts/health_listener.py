import os
import subprocess
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from common Docker and host paths
# Try container path first, fallback to local path
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

# Load Discord bot token and channel ID
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

print("[DEBUG] DISCORD_BOT_TOKEN loaded:", TOKEN is not None)
print("[DEBUG] DISCORD_CHANNEL_ID loaded:", CHANNEL_ID)

# Validate environment variables
if TOKEN is None or CHANNEL_ID is None:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID in environment")

CHANNEL_ID = int(CHANNEL_ID)

# Create bot with message content intent
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
        output = result.stdout.strip() or "[no output]"
        await ctx.send(f"```{output[:1900]}```")
    except Exception as e:
        await ctx.send(f"Health check failed: {e}")

bot.run(TOKEN)
