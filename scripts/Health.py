from dotenv import load_dotenv
import os
import subprocess
import logging
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import psutil
import speedtest

# Load environment variables from ../.env
load_dotenv(dotenv_path="../.env")

# Configure logging
log_file = "/mnt/data/service_status.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load credentials and configuration
deluge_config = {
    "host": "localhost",
    "port": 58846,
    "username": "localclient",
    "password": os.getenv("DELUGE_PASSWORD")
}

plex_config = {
    "url": os.getenv("PLEX_SERVER"),
    "token": os.getenv("PLEX_TOKEN")
}

containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]

def check_docker_running(container):
    print(f"Checking container: {container} ...")
    try:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                                capture_output=True, text=True)
        status = result.stdout.strip() == "true"
        print(f"{container}: {'OK' if status else 'NOT RUNNING'}")
        return status
    except Exception as e:
        print(f"{container}: ERROR - {e}")
        return False

def get_deluge_stats():
    print("Checking Deluge status ...")
    try:
        client = DelugeRPCClient(deluge_config["host"], deluge_config["port"],
                                 deluge_config["username"], deluge_config["password"])
        client.connect()
        torrents = client.call('core.get_torrents_status', {}, ['state'])
        downloading = sum(1 for t in torrents.values() if t[b'state'] == b'Downloading')
        seeding = sum(1 for t in torrents.values() if t[b'state'] == b'Seeding')
        print(f"Deluge OK - Downloading: {downloading}, Seeding: {seeding}")
        return downloading, seeding
    except Exception as e:
        print(f"Deluge ERROR - {e}")
        return None, None

def get_plex_watchers():
    print("Checking Plex sessions ...")
    try:
        plex = PlexServer(plex_config["url"], plex_config["token"])
        watchers = len(plex.sessions())
        print(f"Plex OK - Watchers: {watchers}")
        return watchers
    except Exception as e:
        print(f"Plex ERROR - {e}")
        return None

def get_cpu_usage():
    print("Checking CPU usage ...")
    usage = psutil.cpu_percent(interval=1)
    print(f"CPU Usage: {usage}%")
    return usage

def get_internet_speed():
    print("Checking Internet speed ...")
    try:
        st = speedtest.Speedtest()
        download = st.download() / 1e6
        upload = st.upload() / 1e6
        print(f"Internet OK - Download: {round(download,2)} Mbps, Upload: {round(upload,2)} Mbps")
        return round(download, 2), round(upload, 2)
    except Exception as e:
        print(f"Internet Speed ERROR - {e}")
        return None, None

def log_status():
    print("Starting health checks ...")
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
        "Internet UL Mbps": ul_speed
    }

    logging.info(str(log_data))
    print("Health check completed and logged.")

if __name__ == "__main__":
    log_status()
