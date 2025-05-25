import os
import sys
import re  # Required for regex matching
import socket
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from pathlib import Path

# Setup import path for shared modules
sys.path.append("..")
from discord_notify import send_discord_message

# Setup logging
log_file = "/mnt/data/sev1_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment from known paths
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        break

# Environment and container names
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

# D-001: VPN container check
send_discord_message("Executing check 1/4: Verifying VPN container status...")
if not container_running(VPN_CONTAINER):
    msg = "[D-001] VPN container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-001")
    exit(1)
send_discord_message("Check 1/4 successful.")

# D-002: Deluge container check
send_discord_message("Executing check 2/4: Verifying Deluge container status...")
if not container_running(DELUGE_CONTAINER):
    msg = "[D-002] Deluge container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-002")
    exit(2)
send_discord_message("Check 2/4 successful.")

# D-003: Deluge RPC check
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

# D-004: IP and connectivity validation via external shell script
send_discord_message("Executing check 4/4: Verifying Deluge VPN binding and torrent activity...")

try:
    result = subprocess.run(
        ["bash", "../function/check_deluge_vpn_ip.sh"],
        capture_output=True,
        text=True,
        check=True
    )
    output = result.stdout.strip()
except subprocess.CalledProcessError:
    msg = "[D-004] VPN IP script failed to execute."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Extract IPs
vpn_ip = deluge_ip = host_ip = None
for line in output.splitlines():
    if "VPN_IP" in line:
        vpn_ip = line.split(":")[-1].strip()
    elif "DELUGE_IP" in line:
        deluge_ip = line.split(":")[-1].strip()
    elif "HOST_IP" in line:
        host_ip = line.split(":")[-1].strip()

# Report IPs
debug = "\n".join([
    "[DEBUG] Deluge VPN IP validation:",
    f"VPN IP: {vpn_ip or 'Unavailable'}",
    f"Deluge IP: {deluge_ip or 'Unavailable'}",
    f"Host IP: {host_ip or 'Unavailable'}"
])
send_discord_message(debug)

# Logic: if any IP missing, exit
if not vpn_ip or not deluge_ip or not host_ip:
    msg = "[D-004] IP check failed — incomplete data"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Logic: if Deluge IP == host IP, it's leaking
if deluge_ip == host_ip:
    msg = f"[D-004] Deluge leaking traffic — Deluge IP matches host (VPN: {vpn_ip}, Deluge: {deluge_ip})"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Connectivity test: check if Deluge has torrents seeding/downloading
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    status = client.call("core.get_torrents_status", {}, ["state"])
    downloading = sum(1 for t in status.values() if t[b"state"] == b"Downloading")
    seeding = sum(1 for t in status.values() if t[b"state"] == b"Seeding")
    if downloading == 0 and seeding == 0:
        msg = f"[D-004] Deluge bound to VPN but no torrent activity (DL: {downloading}, SEED: {seeding})"
        logging.warning(msg)
        send_discord_message(msg)
    else:
        msg = f"[D-004] Deluge bound securely and active (VPN: {vpn_ip})"
        logging.info(msg)
        send_discord_message("Check 4/4 successful.")
except Exception as e:
    msg = f"[D-004] Deluge status check failed — {e}"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)