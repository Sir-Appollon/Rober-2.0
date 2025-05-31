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
import json


# Ajout du chemin pour import addmedia
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "addmedia")))

# Mode: "normal" or "debug"
mode = "debug"

# Load environment variables
if not load_dotenv("/app/.env"):
    load_dotenv("../../.env")

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

        subprocess.run(["python3", "/app/scripts/health"], timeout=60)

        await ctx.send("Health check executed.")

    except Exception as e:
        await ctx.send(f"Execution failed: {e}")
        if mode == "debug":
            print(f"[DEBUG - health_listener.py] Exception: {e}")


@bot.command(name="lastdata")
async def get_last_data(ctx):
    if ctx.channel.id != CHANNEL_ID:
        if mode == "debug":
            print(f"[DEBUG - lastdata] Command from unauthorized channel: {ctx.channel.id}")
        return

    log_file = "/mnt/data/system_monitor_log.json"

    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
            last_entry = logs[-1]
            timestamp = last_entry.get("timestamp", "N/A")
            cpu = last_entry["system"]["cpu_total"]
            ram = last_entry["system"]["ram_total"]
            dl = last_entry["network"]["speedtest"]["download_mbps"]
            ul = last_entry["network"]["speedtest"]["upload_mbps"]
            plex_sessions = last_entry["plex"]["active_sessions"]
            deluge_dl = last_entry["deluge"]["download_rate"]
            deluge_ul = last_entry["deluge"]["upload_rate"]

            summary = (
                f"**Dernière entrée du système** ({timestamp})\n"
                f"🖥️ CPU: {cpu}% | 🧠 RAM: {ram}%\n"
                f"🌐 DL: {dl} Mbps | UL: {ul} Mbps\n"
                f"🎞️ Plex sessions: {plex_sessions}\n"
                f"🐌 Deluge: DL: {deluge_dl:.2f} KB/s | UL: {deluge_ul:.2f} KB/s"
            )

            await ctx.send(summary)

    except Exception as e:
        await ctx.send(f"Erreur lecture log: {e}")
        if mode == "debug":
            print(f"[DEBUG - lastdata] Exception: {e}")

# @bot.command(name="addMovie")
# async def add_movie(ctx, *, title):
#     await handle_add_request(ctx, title, content_type="movie")

# @bot.command(name="addTV")
# async def add_tv(ctx, *, title):
#     await handle_add_request(ctx, title, content_type="tv")

# Start bot loop
bot.run(TOKEN)
