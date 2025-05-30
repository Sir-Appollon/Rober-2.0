"""
File: Health_monit.py
Purpose: Automatically evaluate the health of core services (containers, Plex, Deluge, DuckDNS, SSL, NGINX).

Inputs:
- Environment variables: PLEX_SERVER, PLEX_TOKEN, DELUGE_PASSWORD, DOMAIN
- Docker container states
- Network responses (HTTP, SSL)

Outputs:
- Log file: /mnt/data/health_automatic_monitoring.log
- Returns success/failure of critical checks
- Prints debug information if enabled

Triggered Files/Services:
- This is an independent monitor, called periodically or manually
"""

import os
import subprocess
import logging
import ssl
import socket
import requests
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer

# Mode toggle: set to "debug" to enable verbose outputs
mode = "normal"

# Load environment variables
if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

# Setup logging
log_file = "/mnt/data/health_automatic_monitoring.log"
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Environment configurations
containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]
plex_url = os.getenv("PLEX_SERVER")
plex_token = os.getenv("PLEX_TOKEN")
deluge_password = os.getenv("DELUGE_PASSWORD")
domain = os.getenv("DOMAIN")  # e.g., https://yourdomain.duckdns.org

logging.getLogger("deluge_client.client").setLevel(logging.WARNING)

def check_docker(container):
    try:
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] Checking Docker container: {container}")
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                             capture_output=True, text=True)
        result = out.stdout.strip() == "true"
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] Docker {container} running: {result}")
        return result
    except Exception as e:
        logging.error(f"Error checking Docker container {container}: {e}")
        return False

def get_failing_services():
    status = {c: check_docker(c) for c in containers}
    failed = [name for name, ok in status.items() if not ok]
    return status, failed

def check_plex_internal():
    try:
        if mode == "debug":
            print("[DEBUG - Health_monit.py] Checking internal Plex access")
        PlexServer(plex_url, plex_token)
        return True
    except Exception as e:
        logging.error(f"Internal Plex check failed: {e}")
        return False

def check_duckdns():
    try:
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] Checking DuckDNS domain: {domain}")
        r = requests.get(domain, timeout=5, allow_redirects=True)
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] DuckDNS HTTP status: {r.status_code}")
        return r.status_code < 500
    except Exception as e:
        logging.error(f"DuckDNS check failed: {e}")
        return False

def check_ssl():
    try:
        hostname = domain.replace("https://", "").split("/")[0]
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] Checking SSL for: {hostname}")
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(5)
            s.connect((hostname, 443))
            cert = s.getpeercert()
            result = cert is not None
            if mode == "debug":
                print(f"[DEBUG - Health_monit.py] SSL cert presence: {result}")
            return result
    except Exception as e:
        logging.error(f"SSL check failed: {e}")
        return False

def check_plex_remote():
    try:
        if mode == "debug":
            print("[DEBUG - Health_monit.py] Checking remote Plex access")
        response = requests.get(f"{domain}/web", timeout=5, verify=True)
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] Remote Plex HTTP status: {response.status_code}")
        return response.status_code < 500
    except Exception as e:
        logging.error(f"Remote Plex check failed: {e}")
        return False

def check_deluge():
    try:
        if mode == "debug":
            print("[DEBUG - Health_monit.py] Checking Deluge RPC access")
        client = DelugeRPCClient("localhost", 58846, "localclient", deluge_password, False)
        client.connect()
        return True
    except Exception as e:
        logging.error(f"Deluge check failed: {e}")
        return False

def check_nginx():
    try:
        if mode == "debug":
            print("[DEBUG - Health_monit.py] Checking NGINX configuration")
        result = subprocess.run(["docker", "exec", "nginx-proxy", "nginx", "-t"],
                                capture_output=True, text=True)
        output = result.stdout + result.stderr
        ok = "syntax is ok" in output.lower()
        if mode == "debug":
            print(f"[DEBUG - Health_monit.py] NGINX syntax check: {ok}")
        logging.debug(f"Nginx config result: {output.strip()}")
        return ok
    except Exception as e:
        logging.error(f"Nginx check failed: {e}")
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

        if check_nginx():
            logging.info("Nginx configuration valid.")
        else:
            logging.error("Nginx configuration error.")

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
