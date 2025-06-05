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
import sys
import os


# Ajout du chemin pour import addmedia
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "addmedia")))
from add_request_handler import handle_add_request
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

        subprocess.run(["python3", "/app/scripts/health/Health.py"], timeout=60)

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

            # System
            cpu = last_entry["system"]["cpu_total"]
            ram = last_entry["system"]["ram_total"]
            temp = last_entry["system"].get("cpu_temp_c", "N/A")

            # Network
            dl = last_entry["network"]["speedtest"]["download_mbps"]
            ul = last_entry["network"]["speedtest"]["upload_mbps"]

            # Plex
            plex = last_entry["plex"]
            plex_sessions = plex["active_sessions"]
            plex_transcoding = plex["transcoding_sessions"]
            plex_cpu = plex["cpu_usage"]

            # Deluge
            deluge = last_entry["deluge"]
            deluge_dl = deluge["download_rate_kbps"]
            deluge_ul = deluge["upload_rate_kbps"]
            deluge_downloading = deluge["num_downloading"]
            deluge_seeding = deluge["num_seeding"]

            # Storage
            storage = last_entry["storage"]
            storage_lines = ""
            for mount, stats in storage.items():
                size = stats["total_gb"]
                used_pct = stats["used_pct"] if "used_pct" in stats else round((stats["used_gb"] / stats["total_gb"]) * 100, 1)
                label = f"{mount} → {size:.2f} Go" if size < 1024 else f"{mount} → {size/1024:.2f} To"
                storage_lines += f"\n • {label}, utilisé à {used_pct}%"

            # Docker services
            docker = last_entry["docker_services"]
            docker_status = " | ".join([f"{'✅' if state else '❌'} {name}" for name, state in docker.items()])

            # IP match
            vpn_ips = last_entry["network"].get("vpn_ip", [])
            deluge_ips = last_entry["network"].get("deluge_ip", [])
            ip_match = any(ip in vpn_ips for ip in deluge_ips)
            common_ip = next((ip for ip in deluge_ips if ip in vpn_ips), "N/A")

            summary = (
                f"**Dernière entrée du système** (`{timestamp}`)\n"
                f"🖥️ CPU: {cpu}% | 🧠 RAM: {ram}% | 🌡️ Température CPU: {temp}°C\n"
                f"🌐 DL: {dl} Mbps | UL: {ul} Mbps\n"
                f"🎞️ Plex sessions: {plex_sessions}\n"
                f"🎞️ Plex transcoding: {plex_transcoding} | Plex CPU: {plex_cpu}%\n"
                f"🐌 Deluge - Downloading: {deluge_downloading} | Seeding: {deluge_seeding}\n"
                f"\t⬇️ DL: {deluge_dl:.2f} KB/s | ⬆️ UL: {deluge_ul:.2f} KB/s\n"
                f"💾 Stockage :{storage_lines}\n"
                f"🐳 Docker: {docker_status}\n"
                f"🔁 Deluge IP = VPN IP ? {'✅' if ip_match else '❌'} ({common_ip})"
            )

            await ctx.send(summary)

    except Exception as e:
        await ctx.send(f"Erreur lecture log: {e}")
        if mode == "debug":
            print(f"[DEBUG - lastdata] Exception: {e}")


@bot.command(name="addMovie")
async def add_movie(ctx, *, title=None):
    if not title:
        await ctx.send("❗ Utilisation : `!addMovie <titre du film>`")
        return
    await handle_add_request("movie", title, ctx.channel)


@bot.command(name="addTV")
async def add_tv(ctx, *, title=None):
    if not title:
        await ctx.send("❗ Utilisation : `!addTV <titre de la série>`")
        return
    await handle_add_request("tv", title, ctx.channel)

# Start bot loop
bot.run(TOKEN)
