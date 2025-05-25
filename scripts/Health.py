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
# Try container path first, fallback to host path
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

# DEBUG: Check loaded critical env variables
print("[DEBUG] DISCORD_WEBHOOK:", os.getenv("DISCORD_WEBHOOK"))
print("[DEBUG] PLEX_SERVER:", os.getenv("PLEX_SERVER"))
print("[DEBUG] PLEX_TOKEN:", os.getenv("PLEX_TOKEN"))
print("[DEBUG] DELUGE_PASSWORD:", os.getenv("DELUGE_PASSWORD"))

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
    print(f"[DEBUG] Checking container: {container} ...")
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip() == "true"
        print(f"[DEBUG] {container}: {'OK' if status else 'NOT RUNNING'}")
        return status
    except Exception as e:
        print(f"[DEBUG] {container} ERROR - {e}")
        return False

def get_deluge_stats():
    print("[DEBUG] Checking Deluge status ...")
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
        print(f"[DEBUG] Deluge OK - Downloading: {downloading}, Seeding: {seeding}")
        return downloading, seeding
    except Exception as e:
        print(f"[DEBUG] Deluge ERROR - {e}")
        return None, None

def get_plex_watchers():
    print("[DEBUG] Checking Plex sessions ...")
    try:
        plex = PlexServer(plex_config["url"], plex_config["token"])
        watchers = len(plex.sessions())
        print(f"[DEBUG] Plex OK - Watchers: {watchers}")
        return watchers
    except Exception as e:
        print(f"[DEBUG] Plex ERROR - {e}")
        return None

def get_cpu_usage():
    print("[DEBUG] Checking CPU usage ...")
    usage = psutil.cpu_percent(interval=1)
    print(f"[DEBUG] CPU Usage: {usage}%")
    return usage

def get_internet_speed():
    print("[DEBUG] Checking Internet speed ...")
    try:
        st = speedtest.Speedtest()
        download = st.download() / 1e6
        upload = st.upload() / 1e6
        print(f"[DEBUG] Internet OK - Download: {round(download, 2)} Mbps, Upload: {round(upload, 2)} Mbps")
        return round(download, 2), round(upload, 2)
    except Exception as e:
        print(f"[DEBUG] Internet Speed ERROR - {e}")
        return None, None

def log_status():
    print("[DEBUG] Starting health checks ...")
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
    print("[DEBUG] Health check completed and logged.")

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

    print(f"[DEBUG] Sending message to Discord:\n{message}")
    send_discord_message(message)

if __name__ == "__main__":
    log_status()