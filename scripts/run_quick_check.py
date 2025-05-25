import os
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
from discord_notify import send_discord_message


# Logging setup
log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# Load environment variables
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

# Credentials
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

# Container check
def check_container(name):
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == "true"
    except:
        return False

def check_all_containers():
    return all(check_container(c) for c in containers)

# Service checks
def check_plex_local():
    try:
        PlexServer(plex_config["url"], plex_config["token"])
        return True
    except:
        return False

def check_deluge_rpc():
    try:
        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False
        )
        client.connect()
        return True
    except:
        return False

def check_radarr_sonarr():
    radarr = check_container("radarr")
    sonarr = check_container("sonarr")
    return radarr and sonarr

# Execution logic
if not check_plex_local():
    logging.info("SEV 0: Plex not responding locally.")
    send_discord_message("[SEV 0] Plex access failure detected — detailed diagnostic in progress.")
    subprocess.run(["python3", "/app/sev/sev0.py"])
    print("FAILURE")

elif not check_deluge_rpc():
    logging.info("SEV 1: Deluge RPC unreachable.")
    send_discord_message("[SEV 1] Deluge not responding — diagnostic triggered.")
    subprocess.run(["python3", "/app/sev/sev1.py"])
    print("FAILURE")

elif not check_radarr_sonarr():
    logging.info("SEV 2: Radarr or Sonarr not responding.")
    send_discord_message("[SEV 2] Radarr/Sonarr failure detected — diagnostic triggered.")
    subprocess.run(["python3", "/app/sev/sev2.py"])
    print("FAILURE")

elif not check_all_containers():
    logging.info("SEV 3: One or more containers not running.")
    send_discord_message("[SEV 3] Core container failure — diagnostic triggered.")
    subprocess.run(["python3", "/app/sev/sev3.py"])
    print("FAILURE")

else:
    logging.info("OK: All quick checks passed.")
    send_discord_message("[DEBUG] QuickCheck: all systems operational")
    print("OK")
