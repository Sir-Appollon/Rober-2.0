"""
File: sev1.py
Purpose: Diagnose and attempt recovery from Deluge or VPN service failure (SEV 1).

Inputs:
- Environment variables: DELUGE_PASSWORD
- Docker containers: vpn, deluge
- Deluge RPC port (58846)
- Deluge core.conf for outgoing interface

Outputs:
- Logs diagnostic output to /mnt/data/sev1_diagnostic.log
- Sends messages via Discord
- Invokes resolution scripts (sev1_resolution.py) when failures are detected

Triggered Files/Services:
- Discord notifications via scripts/discord/discord_notify.py
- Resolution script sev1_resolution.py
"""

import os
import sys
import time
import json
import re
import logging
import subprocess
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from pathlib import Path

# Mode: "normal" or "debug"
mode = "normal"

# Fix path to import notifier
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))


# Logging setup
log_file = "/mnt/data/sev1_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        if mode == "debug":
            print(f"[DEBUG - sev1.py] Loaded .env from {path}")
        break

# Constants
VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"
DELUGE_USER = "localclient"
DELUGE_PASS = os.getenv("DELUGE_PASSWORD")

# Notify start
send_discord_message("Initiating SEV 1 diagnostic sequence for Deluge/VPN failure.")

def container_running(name):
    try:
        if mode == "debug":
            print(f"[DEBUG - sev1.py] Checking container: {name}")
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
        running = result.stdout.strip() == "true"
        if mode == "debug":
            print(f"[DEBUG - sev1.py] {name} running: {running}")
        return running
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - sev1.py] Error checking {name}: {e}")
        return False

def run_resolution(code):
    send_discord_message(f"[{code}] Triggering automated resolution routine...")
    if mode == "debug":
        print(f"[DEBUG - sev1.py] Running resolution for {code}")
    subprocess.run(["python3", "/app/scripts/SEV/Resolution/sev1_resolution.py", code])

# D-001 — VPN container check
send_discord_message("Executing check 1/4: Verifying VPN container status...")
if not container_running(VPN_CONTAINER):
    msg = "[D-001] VPN container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-001")
    exit(1)
send_discord_message("Check 1/4 successful.")

# D-002 — Deluge container check
send_discord_message("Executing check 2/4: Verifying Deluge container status...")
if not container_running(DELUGE_CONTAINER):
    msg = "[D-002] Deluge container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-002")
    exit(2)
send_discord_message("Check 2/4 successful.")

# D-003 — Deluge RPC access
send_discord_message("Executing check 3/4: Testing Deluge RPC connection...")
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    if mode == "debug":
        print("[DEBUG - sev1.py] Deluge RPC connection successful.")
except Exception as e:
    msg = "[D-003] Deluge RPC error — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-003")
    if mode == "debug":
        print(f"[DEBUG - sev1.py] RPC connection failed: {e}")
    exit(3)
send_discord_message("Check 3/4 successful.")

# D-004 — Validate Deluge VPN binding and internet access
send_discord_message("Executing check 4/4: Checking Deluge IP binding and internet access...")

def get_outgoing_ip_from_coreconf():
    try:
        with open("/config/deluge/core.conf", "r") as f:
            config = json.load(f)
            ip = config.get("outgoing_interface")
            if mode == "debug":
                print(f"[DEBUG - sev1.py] Deluge config outgoing_interface: {ip}")
            return ip
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - sev1.py] Error reading core.conf: {e}")
        send_discord_message(f"[DEBUG] Failed to read Deluge config: {e}")
        return None

def get_vpn_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        ip = match.group(1) if match else None
        if mode == "debug":
            print(f"[DEBUG - sev1.py] VPN tun0 IP: {ip}")
        return ip
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - sev1.py] Error getting VPN IP: {e}")
        return None

def deluge_can_access_internet():
    try:
        result = subprocess.run(
            ["docker", "exec", DELUGE_CONTAINER, "curl", "-s", "--max-time", "5", "https://www.google.com"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if mode == "debug":
            print(f"[DEBUG - sev1.py] curl return code: {result.returncode}")
        return result.returncode == 0
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - sev1.py] curl exception: {e}")
        return False

deluge_ip = get_outgoing_ip_from_coreconf()
vpn_ip = get_vpn_ip()

send_discord_message(f"[DEBUG] Deluge config IP: {deluge_ip}")
send_discord_message(f"[DEBUG] VPN IP (tun0): {vpn_ip}")

if not deluge_ip or not vpn_ip:
    msg = "[D-004] IP mismatch check failed — unable to extract IPs."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

if deluge_ip != vpn_ip:
    msg = f"[D-004] Deluge IP mismatch — Deluge: {deluge_ip}, VPN: {vpn_ip}"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

if not deluge_can_access_internet():
    msg = "[D-004] Deluge cannot access the internet — possible VPN misroute."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

msg = "[D-004] Deluge is correctly bound to VPN and has internet access."
logging.info(msg)
send_discord_message("Check 4/4 successful.")

# Final status
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)
