"""
File: health_listener.py
Purpose: Discord bot that listens for the "!health" command and triggers system health check.

Inputs:
- Discord bot messages from a specific channel
- Environment variables:
  - DISCORD_BOT_TOKEN
  - DISCORD_CHANNEL_ID

Outputs:
- Executes Health.py when triggered
- Sends command response status to Discord

Triggered Files/Services:
- Executes scripts/health/Health.py
"""

import subprocess
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Mode: "normal" or "debug"
mode = "normal"

# Load environment variables
if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

# Get bot token and target channel
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# Configure bot intents and prefix
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    if mode == "debug":
        print("[DEBUG - health_listener.py] Discord bot connected and ready.")

@bot.command(name="health")
async def run_health(ctx):
    if ctx.channel.id != CHANNEL_ID:
        if mode == "debug":
            print(f"[DEBUG - health_listener.py] Command from unauthorized channel: {ctx.channel.id}")
        return

    await ctx.send("Running health check...")

    try:
        if mode == "debug":
            print("[DEBUG - health_listener.py] Launching Health.py via subprocess.")

        subprocess.run(["python3", "/app/scripts/health/Health.py"], timeout=60)

        await ctx.send("Health check executed.")

    except Exception as e:
        await ctx.send(f"Execution failed: {e}")
        if mode == "debug":
            print(f"[DEBUG - health_listener.py] Exception: {e}")

# Start bot loop
bot.run(TOKEN)
