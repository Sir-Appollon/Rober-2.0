"""
File: Health.py
Purpose: On-demand system health check reporting service status, Deluge activity, Plex sessions, CPU usage, and network speed.

Inputs:
- Environment variables: DELUGE_PASSWORD, PLEX_SERVER, PLEX_TOKEN
- Docker container statuses
- Deluge RPC
- Plex API
- System metrics via psutil
- Speedtest CLI

Outputs:
- Logs results to /mnt/data/entry_log_health.log
- Sends status report to Discord via webhook
- Prints debug output if mode is set to "debug"

Triggered Files/Services:
- Called manually or via Discord bot (health_listener.py)
- Sends message using scripts/discord/discord_notify.py
"""

import os
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import psutil
import speedtest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))



# Mode: "normal" or "debug"
mode = "normal"

# Load environment
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../../.env")

# Setup logging
log_file = "/mnt/data/entry_log_health.log"
logging.basicConfig(
    filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s"
)

# Deluge and Plex configuration
deluge_config = {
    "host": "localhost",
    "port": 58846,
    "username": "localclient",
    "password": os.getenv("DELUGE_PASSWORD"),
}

plex_config = {
    "url": os.getenv("PLEX_SERVER"),
    "token": os.getenv("PLEX_TOKEN"),
}

containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]

def check_docker_running(container):
    if mode == "debug":
        print(f"[DEBUG - Health.py] Checking container: {container}")
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip() == "true"
        if mode == "debug":
            print(f"[DEBUG - Health.py] {container} status: {'OK' if status else 'NOT RUNNING'}")
        return status
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - Health.py] {container} ERROR - {e}")
        return False

def get_deluge_stats():
    if mode == "debug":
        print("[DEBUG - Health.py] Checking Deluge status")
    try:
        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False
        )
        client.connect()
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        downloading = sum(1 for t in torrents.values() if t[b"state"] == b"Downloading")
        seeding = sum(1 for t in torrents.values() if t[b"state"] == b"Seeding")
        if mode == "debug":
            print(f"[DEBUG - Health.py] Deluge - Downloading: {downloading}, Seeding: {seeding}")
        return downloading, seeding
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - Health.py] Deluge ERROR - {e}")
        return None, None

def get_plex_watchers():
    if mode == "debug":
        print("[DEBUG - Health.py] Checking Plex sessions")
    try:
        plex = PlexServer(plex_config["url"], plex_config["token"])
        watchers = len(plex.sessions())
        if mode == "debug":
            print(f"[DEBUG - Health.py] Plex Watchers: {watchers}")
        return watchers
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - Health.py] Plex ERROR - {e}")
        return None

def get_cpu_usage():
    if mode == "debug":
        print("[DEBUG - Health.py] Checking CPU usage")
    usage = psutil.cpu_percent(interval=1)
    if mode == "debug":
        print(f"[DEBUG - Health.py] CPU Usage: {usage}%")
    return usage

def get_internet_speed():
    if mode == "debug":
        print("[DEBUG - Health.py] Running speedtest")
    try:
        result = subprocess.run(["speedtest", "--simple"], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        dl = float(lines[1].split()[1])
        ul = float(lines[2].split()[1])
        if mode == "debug":
            print(f"[DEBUG - Health.py] Speedtest DL: {dl} Mbps, UL: {ul} Mbps")
        return dl, ul
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - Health.py] Speedtest CLI failed: {e}")
        return None, None

def log_status():
    if mode == "debug":
        print("[DEBUG - Health.py] Starting health check...")

    statuses = {c: check_docker_running(c) for c in containers}
    deluge_down, deluge_seed = get_deluge_stats()
    plex_watchers = get_plex_watchers()
    cpu = get_cpu_usage()
    dl_speed, ul_speed = get_internet_speed()

    log_data = {
        "Docker Status": statuses,
        "Deluge Downloading": deluge_down,
        "Deluge Seeding": deluge_seed,
        "Plex Watchers": plex_watchers,
        "CPU Usage %": cpu,
        "Internet DL Mbps": dl_speed,
        "Internet UL Mbps": ul_speed,
    }

    logging.info(str(log_data))

    if mode == "debug":
        print(f"[DEBUG - Health.py] Final Log Data: {log_data}")

    message = "\n".join(
        [
            "**[Health Report]**",
            f"Plex Watchers: {plex_watchers}",
            f"Deluge - Downloading: {deluge_down}, Seeding: {deluge_seed}",
            f"CPU Usage: {cpu}%",
            f"Internet - DL: {dl_speed} Mbps, UL: {ul_speed} Mbps",
            "Docker Status:",
            "\n".join([f" - {name}: {'OK' if state else 'DOWN'}" for name, state in statuses.items()]),
        ]
    )

    if mode == "debug":
        print(f"[DEBUG - Health.py] Sending message to Discord:\n{message}")
    send_discord_message(message)

if __name__ == "__main__":
    log_status()
