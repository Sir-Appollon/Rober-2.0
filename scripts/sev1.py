import os
import subprocess
import logging
from dotenv import load_dotenv
import sys
from deluge_client import DelugeRPCClient
from pathlib import Path

# Setup import path
sys.path.append("..")
from discord_notify import send_discord_message

# Setup logging
log_file = "/mnt/data/sev1_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment
env_loaded = False
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        break

VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"
DELUGE_USER = "localclient"
DELUGE_PASS = os.getenv("DELUGE_PASSWORD")

send_discord_message("Initiating SEV 1 diagnostic sequence for Deluge/VPN failure.")

def container_running(name):
    try:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
        return result.stdout.strip() == "true"
    except:
        return False

def run_resolution(code):
    send_discord_message(f"[{code}] Triggering automated resolution routine...")
    subprocess.run(["python3", "sev1_resolution.py", code])

# D-001
send_discord_message("Executing check 1/4: Verifying VPN container status...")
if not container_running(VPN_CONTAINER):
    msg = "[D-001] VPN container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-001")
    exit(1)
send_discord_message("Check 1/4 successful.")

# D-002
send_discord_message("Executing check 2/4: Verifying Deluge container status...")
if not container_running(DELUGE_CONTAINER):
    msg = "[D-002] Deluge container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-002")
    exit(2)
send_discord_message("Check 2/4 successful.")

# D-003
send_discord_message("Executing check 3/4: Testing Deluge RPC connection...")
def deluge_rpc_accessible():
    try:
        client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
        client.connect()
        return True
    except:
        return False

if not deluge_rpc_accessible():
    msg = "[D-003] Deluge RPC error — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-003")
    exit(3)
send_discord_message("Check 3/4 successful.")

# D-004
send_discord_message("Executing check 4/4: Comparing Deluge and VPN container IPs...")
def get_ip(container):
    try:
        result = subprocess.run(["docker", "exec", container, "sh", "-c", "hostname -i"], capture_output=True, text=True)
        return result.stdout.strip().split()[0]
    except:
        return None

import ipaddress

vpn_ip = get_ip(VPN_CONTAINER)
deluge_ip = get_ip(DELUGE_CONTAINER)

def is_host_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return (
            addr.is_private and
            not ip.startswith("10.") and  # allow 10.x.x.x for VPN
            (ip.startswith("192.168.") or ip.startswith("172."))
        )
    except:
        return False

if not vpn_ip or not deluge_ip or vpn_ip != deluge_ip or is_host_ip(deluge_ip):
    msg = f"[D-004] Deluge leaking traffic — IP invalid or mismatched (VPN: {vpn_ip}, Deluge: {deluge_ip}) — attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

msg = f"[D-004] Deluge bound to VPN IP (secure): {deluge_ip}"
logging.info(msg)
send_discord_message("Check 4/4 successful.")

logging.info(msg)
send_discord_message("Check 4/4 successful.")
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected. No further action required.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected. No further action required.")
exit(0)
