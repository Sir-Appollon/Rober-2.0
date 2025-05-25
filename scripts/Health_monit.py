import os
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import psutil
import requests

# Load environment
if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

# Logging setup
log_file = "/mnt/data/service_status.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# Config
containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]
plex_url = os.getenv("PLEX_SERVER")
plex_token = os.getenv("PLEX_TOKEN")
deluge_password = os.getenv("DELUGE_PASSWORD")
domain = os.getenv("DOMAIN")  # for duckdns/ssl

def check_docker(container):
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                             capture_output=True, text=True)
        return out.stdout.strip() == "true"
    except:
        return False

def get_failing_services():
    status = {c: check_docker(c) for c in containers}
    failed = [name for name, ok in status.items() if not ok]
    return status, failed

def check_plex_internal():
    try:
        PlexServer(plex_url, plex_token)
        return True
    except:
        return False

def check_duckdns():
    try:
        response = requests.get(domain, timeout=5)
        return response.status_code == 200
    except:
        return False

def check_ssl():
    try:
        out = subprocess.run(["openssl", "s_client", "-connect", f"{domain.replace('https://', '')}:443"],
                             capture_output=True, text=True, timeout=5)
        return "BEGIN CERTIFICATE" in out.stdout
    except:
        return False

def check_plex_remote():
    try:
        out = subprocess.run(["curl", "-fsSL", f"{domain}/web"], capture_output=True)
        return out.returncode == 0
    except:
        return False

def check_deluge():
    try:
        client = DelugeRPCClient("localhost", 58846, "localclient", deluge_password, False)
        client.connect()
        return True
    except:
        return False

def log_status():
    status, failed = get_failing_services()
    if not failed:
        logging.info("All services running.")
    else:
        msg = f"{len(failed)}/{len(containers)} services failed: {', '.join(failed)}"
        logging.error(msg)

    if status.get("plex-server"):
        if not check_plex_internal():
            logging.error("Plex server not responding locally.")
            return

        duckdns_ok = check_duckdns()
        ssl_ok = check_ssl()
        if duckdns_ok and ssl_ok:
            if check_plex_remote():
                logging.info("Plex accessible externally.")
            else:
                logging.error("Plex not accessible remotely.")
        else:
            if not duckdns_ok:
                logging.error("DuckDNS domain not resolving.")
            if not ssl_ok:
                logging.error("SSL certificate invalid or expired.")

    if status.get("vpn"):
        if status.get("deluge"):
            if check_deluge():
                logging.info("Deluge working behind VPN.")
            else:
                logging.error("Deluge running but RPC not responding.")
        else:
            logging.error("Deluge container down.")
    else:
        logging.error("VPN container down.")

if __name__ == "__main__":
    log_status()
