import os
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import psutil
import speedtest
from discord_notify import send_discord_message

# Load environment variables from container or host
if not load_dotenv("/app/.env"):
    load_dotenv(dotenv_path="../.env")

# Configure logging
log_file = "/mnt/data/service_status.log"
logging.basicConfig(
    filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s"
)

# Load credentials
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
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False

def get_deluge_stats():
    try:
        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False  # No SSL
        )
        client.connect()
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        downloading = sum(1 for t in torrents.values() if t[b"state"] == b"Downloading")
        seeding = sum(1 for t in torrents.values() if t[b"state"] == b"Seeding")
        return downloading, seeding
    except Exception:
        return None, None

def get_plex_watchers():
    try:
        plex = PlexServer(plex_config["url"], plex_config["token"])
        return len(plex.sessions())
    except Exception:
        return None

def get_cpu_usage():
    return psutil.cpu_percent(interval=1)

def get_internet_speed():
    try:
        st = speedtest.Speedtest()
        download = st.download() / 1e6
        upload = st.upload() / 1e6
        return round(download, 2), round(upload, 2)
    except Exception:
        return None, None

def log_status():
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

    send_discord_message(message)

if __name__ == "__main__":
    log_status()
