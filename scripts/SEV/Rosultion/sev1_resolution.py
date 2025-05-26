"""
File: sev1_resolution.py
Purpose: Attempt automated resolution of issues identified in SEV 1 diagnostics.

Inputs:
- Environment variables (from .env)
- Resolution code passed via CLI (e.g., D-001)

Outputs:
- Logs actions to /mnt/data/sev1_resolution.log
- Sends resolution status via Discord

Triggered Files/Services:
- Docker containers: vpn, deluge
- Scripts: ip_adress_up.py (used by D-004)
- Discord notifications via scripts/discord/discord_notify.py
"""

import os
import sys
import re
import time
import subprocess
import logging
from dotenv import load_dotenv
from pathlib import Path

# Set mode: "debug" or "normal"
mode = "normal"

# Add script path
sys.path.append("/app/scripts")
from scripts.discord.discord_notify import send_discord_message

# Logging setup
log_file = "/mnt/data/sev1_resolution.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load .env from standard locations
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        if mode == "debug":
            print(f"[DEBUG - sev1_resolution.py] Loaded .env from {path}")
        break

DELUGE_PASSWORD = os.getenv("DELUGE_PASSWORD")
VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"

def tail_logs(container, lines=5):
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container],
            capture_output=True, text=True
        )
        return result.stdout.strip().splitlines()[-1]
    except:
        return "[Log tail unavailable]"

def resolve_d001():
    log = tail_logs(VPN_CONTAINER)
    msg = f"[D-001 - Resolution Failed] VPN is not running.\nLast log: {log}"
    logging.error(msg)
    send_discord_message(msg)

def resolve_d002():
    log = tail_logs(DELUGE_CONTAINER)
    msg = f"[D-002 - Resolution Failed] Deluge is not running.\nLast log: {log}"
    logging.error(msg)
    send_discord_message(msg)

def resolve_d003():
    try:
        subprocess.run(["docker", "restart", DELUGE_CONTAINER], check=True)
        msg = "[D-003 - Resolution Completed] Deluge restarted to restore RPC."
        logging.info(msg)
        send_discord_message(msg)
    except Exception as e:
        msg = f"[D-003 - Resolution Failed] Deluge restart failed. {str(e)}"
        logging.error(msg)
