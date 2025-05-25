import os
import subprocess
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import logging
from discord_notify import send_discord_message


log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# Load environment variables from container or host
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

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

if not check_all_containers():
    logging.info("FAILURE: One or more containers not running.")
    send_discord_message("[DEBUG] QuickCheck: container failure")
    print("FAILURE")
elif not check_plex_local():
    logging.info("FAILURE: Plex not responding locally.")
    send_discord_message("[DEBUG] QuickCheck: Plex not responding")
    print("FAILURE")
elif not check_deluge_rpc():
    logging.info("FAILURE: Deluge RPC unreachable.")
    send_discord_message("[DEBUG] QuickCheck: Deluge RPC unreachable")
    print("FAILURE")
else:
    logging.info("OK: All quick checks passed.")
    send_discord_message("[DEBUG] QuickCheck: all OK")
    print("OK")


