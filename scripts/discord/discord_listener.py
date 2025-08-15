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

# Ajout du chemin pour import
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from addmedia.add_request_handler import handle_add_request
from adduser.plex_invite import invite_user

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


# @bot.command(name="health")
# async def run_health(ctx):
#     if ctx.channel.id != CHANNEL_ID:
#         if mode == "debug":
#             print(
#                 f"[DEBUG - health_listener.py] Command from unauthorized channel: {ctx.channel.id}"
#             )
#         return
#
#     await ctx.send("Running health check...")
#
#     try:
#         if mode == "debug":
#             print("[DEBUG - health_listener.py] Launching Health.py via subprocess.")
#
#         subprocess.run(["python3", "/app/scripts/health/Health.py"], timeout=60)
#
#         await ctx.send("Health check executed.")
#
#     except Exception as e:
#         await ctx.send(f"Execution failed: {e}")
#         if mode == "debug":
#             print(f"[DEBUG - health_listener.py] Exception: {e}")

@bot.command(name="plex_online")
async def run_plex_online(ctx):
    # Vérifie si l'ID du canal est autorisé
    if ctx.channel.id != CHANNEL_ID:
        if mode == "debug":
            print(
                f"[DEBUG - plex_online_listener.py] Command from unauthorized channel: {ctx.channel.id}"
            )
        return

    # Message Discord indiquant le début du test
    await ctx.send("Running Plex online check...")

    try:
        if mode == "debug":
            print("[DEBUG - plex_online_listener.py] Launching plex_online.py via subprocess.")

        # Appelle le script Plex avec un timeout de 60 secondes
        subprocess.run(
            ["python3", "/app/health/repair.py", "--plex-online"],
            timeout=60,
            capture_output=True,
            text=True
        )
        # Message de confirmation
        await ctx.send("Plex online check executed.")

    except Exception as e:
        await ctx.send(f"Execution failed: {e}")
        if mode == "debug":
            print(f"[DEBUG - plex_online_listener.py] Exception: {e}")


@bot.command(name="lastdata")
async def get_last_data(ctx):
    if ctx.channel.id != CHANNEL_ID:
        if mode == "debug":
            print(
                f"[DEBUG - lastdata] Command from unauthorized channel: {ctx.channel.id}"
            )
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
            plex_local_acess = plex["local_access"]
            plex_external_acess = plex["external_access"]

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
                used_pct = (
                    stats["used_pct"]
                    if "used_pct" in stats
                    else round((stats["used_gb"] / stats["total_gb"]) * 100, 1)
                )
                label = (
                    f"{mount} → {size:.2f} Go"
                    if size < 1024
                    else f"{mount} → {size/1024:.2f} To"
                )
                storage_lines += f"\n • {label}, utilisé à {used_pct}%"

            # Docker services
            docker = last_entry["docker_services"]
            docker_status = " | ".join(
                [f"{'✅' if state else '❌'} {name}" for name, state in docker.items()]
            )

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
                f"🖳 Plex is locally accessible: {plex_local_acess} | 📡 Plex is exernally accessible: {plex_external_acess}\n"
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
        await ctx.send("❗ Usage: `!addMovie <movie title>`")
        return

    await ctx.send("⏳ Attempting to add the movie...")

    try:
        result = await handle_add_request("movie", title, ctx.channel, bot)
        if result is False:
            await ctx.send("⚠️ The function was called but failed.")
        else:
            await ctx.send("✅ Movie successfully added.")
    except Exception as e:
        await ctx.send(f"❌ Error occurred before or during the function call: {e}")


@bot.command(name="adduser")
async def add_user(ctx, *, email=None):
    if not email:
        await ctx.send("❗ Usage: `!adduser user@example.com`")
        return

    await ctx.send(f"📨 Sending Plex invite to `{email}`...")

    status, response = invite_user(email)
    if status == 201:
        await ctx.send("✅ Invite sent successfully.")
    elif status == 409:
        await ctx.send("⚠️ User already invited or has access.")
    else:
        await ctx.send(
            f"❌ Invite failed (status {status}). Details:\n```{response}```"
        )


# Start bot loop
bot.run(TOKEN)
