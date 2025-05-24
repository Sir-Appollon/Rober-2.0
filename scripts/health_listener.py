import subprocess
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables from container or host path
if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

# Get token and channel ID from environment
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

if not TOKEN or not CHANNEL_ID:
    raise RuntimeError("Missing DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID in .env")

CHANNEL_ID = int(CHANNEL_ID)

# Set up bot with message content intent
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[DEBUG] Logged in as {bot.user}")

@bot.command(name="health")
async def run_health(ctx):
    if ctx.channel.id != CHANNEL_ID:
        print(f"[DEBUG] Ignored command from channel: {ctx.channel.id}")
        return

    await ctx.send("Running health check...")

    try:
        result = subprocess.run(
            ["python3", "/app/Health.py"],
            capture_output=True,
            text=True,
            timeout=60
        )
        stdout = result.stdout.strip() or "[no stdout]"
        stderr = result.stderr.strip()
        report = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}" if stderr else stdout

        if len(report) < 1900:
            await ctx.send(f"```{report}```")
        else:
            import io
            await ctx.send("Output too long. See attached file.")
            await ctx.send(file=discord.File(fp=io.StringIO(report), filename="health_report.txt"))

    except Exception as e:
        await ctx.send(f"Health check failed: {e}")

bot.run(TOKEN)
