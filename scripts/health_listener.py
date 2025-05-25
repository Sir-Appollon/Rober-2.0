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
    pass  # silence bot connection print

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
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Filter out any debug lines from Health.py
        report_lines = [
            line for line in stdout.splitlines() if not line.startswith("[DEBUG]")
        ]
        report = "\n".join(report_lines).strip()

        if stderr:
            report += f"\n\n[ERROR]\n{stderr.strip()}"

        if not report:
            report = "[No output]"

        if len(report) < 1900:
            await ctx.send(f"```{report}```")
        else:
            import io
            await ctx.send("Output too long. See attached file.")
            await ctx.send(file=discord.File(fp=io.StringIO(report), filename="health_report.txt"))

    except Exception as e:
        await ctx.send(f"Health check failed: {e}")

bot.run(TOKEN)
