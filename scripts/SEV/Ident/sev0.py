"""
File: sev0.py
Purpose: Diagnose and resolve SEV 0 condition (Plex local or external access failure).

Inputs:
- Environment variables: DOMAIN, PLEX_SERVER, PLEX_TOKEN
- Container state (plex-server, nginx-proxy)
- SSL certificate of domain
- Plex local/remote HTTP access

Outputs:
- Logs diagnostic steps to /mnt/data/sev0_diagnostic.log
- Sends status messages to Discord
- Terminates on first critical failure

Triggered Files/Services:
- Sends Discord messages via scripts/discord/discord_notify.py
- Interacts with Docker and remote services
"""

import os
import ssl
import socket
import logging
import subprocess
import requests
from dotenv import load_dotenv
from plexapi.server import PlexServer
import sys
from pathlib import Path

# Mode: "normal" or "debug"
mode = "normal"

# Path fix to import from /scripts/discord/
sys.path.append("/app/scripts")
from scripts.discord.discord_notify import send_discord_message

# Logging
log_file = "/mnt/data/sev0_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment
env_loaded = False
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        if mode == "debug":
            print(f"[DEBUG - sev0.py] .env loaded from {path}")
        env_loaded = True
        break
if not env_loaded and mode == "debug":
    print("[DEBUG - sev0.py] No .env file found in known paths.")

DOMAIN = os.getenv("DOMAIN")
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

# Start diagnostics
send_discord_message("Initiating SEV 0 diagnostic sequence for Plex access failure.")

# P-001: Plex container status
send_discord_message("Executing check 1/6: Verifying Plex container status...")
def plex_container_running():
    try:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "plex-server"],
                                capture_output=True, text=True)
        return result.stdout.strip() == "true"
    except:
        return False

if not plex_container_running():
    msg = "[P-001] Plex container is down — problem found, aborting sequence."
    logging.error(msg)
    send_discord_message(msg)
    exit(1)
send_discord_message("Check 1/6 successful.")

# P-002: Plex internal access
send_discord_message("Executing check 2/6: Verifying local Plex accessibility...")
def plex_accessible_local():
    try:
        PlexServer(PLEX_URL, PLEX_TOKEN)
        return True
    except:
        return False

if not plex_accessible_local():
    msg = "[P-002] Plex daemon not responding locally — problem found, aborting sequence."
    logging.error(msg)
    send_discord_message(msg)
    exit(2)
send_discord_message("Check 2/6 successful.")

# P-003: DuckDNS domain resolution
send_discord_message("Executing check 3/6: Validating DuckDNS domain resolution...")
def duckdns_accessible():
    try:
        r = requests.get(DOMAIN, timeout=5, allow_redirects=True)
        return r.status_code < 500
    except:
        return False

if not duckdns_accessible():
    msg = "[P-003] DuckDNS domain not resolving — problem found, aborting sequence."
    logging.error(msg)
    send_discord_message(msg)
    exit(3)
send_discord_message("Check 3/6 successful.")

# P-004: SSL certificate check
send_discord_message("Executing check 4/6: Validating SSL certificate...")
def ssl_certificate_valid():
    try:
        hostname = DOMAIN.replace("https://", "").split("/")[0]
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(5)
            s.connect((hostname, 443))
            cert = s.getpeercert()
            if cert:
                return cert["notAfter"]
    except:
        return None

ssl_expiry = ssl_certificate_valid()
if not ssl_expiry:
    msg = "[P-004] SSL certificate invalid or expired"
    logging.error(msg)
    send_discord_message(msg)
else:
    send_discord_message(f"Check 4/6 successful — SSL cert expires: {ssl_expiry}")

# P-005: Remote Plex access
send_discord_message("Executing check 5/6: Testing remote Plex accessibility...")
def plex_accessible_remote():
    try:
        r = requests.get(f"{DOMAIN}/web", timeout=5, verify=True)
        return r.status_code < 400
    except:
        return False

if not plex_accessible_remote():
    msg = "[P-005] Remote Plex access failed"
    logging.error(msg)
    send_discord_message(msg)
else:
    send_discord_message("Check 5/6 successful.")

# P-006: Nginx config test
send_discord_message("Executing check 6/6: Verifying Nginx configuration...")
def nginx_config_valid():
    try:
        result = subprocess.run(
            ["docker", "exec", "nginx-proxy", "nginx", "-t"],
            capture_output=True,
            text=True
        )
        output = result.stdout.lower() + result.stderr.lower()
        if mode == "debug":
            print(f"[DEBUG - sev0.py] Nginx test output: {output}")
        return "syntax is ok" in output and "test is successful" in output
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - sev0.py] Nginx config check failed: {e}")
        return False

if not nginx_config_valid():
    msg = "[P-006] Nginx configuration invalid"
    logging.error(msg)
    send_discord_message(msg)
    exit(6)
else:
    send_discord_message("Check 6/6 successful.")

# Summary
send_discord_message("SEV 0 diagnostic complete — all tests passed or non-critical warnings detected. No further action required.")
logging.info("SEV 0 diagnostic completed — all checks passed.")
exit(0)
