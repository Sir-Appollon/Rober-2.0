import os
import sys
import re  # Required for regex matching
import socket
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from pathlib import Path
import tempfile
import socket

def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return None

def get_vpn_tun_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        return match.group(1) if match else None
    except:
        return None


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

# # D-004: Deluge activity confirmation

# send_discord_message("Executing check 4/4: Verifying active Deluge download or seeding...")

# try:
#     client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
#     client.connect()
#     torrents = client.call("core.get_torrents_status", {}, ["state"])
#     active = any(t[b"state"] in [b"Downloading", b"Seeding"] for t in torrents.values())
# except Exception as e:
#     msg = "[D-004] Deluge RPC access failed during activity check."
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# if not active:
#     msg = "[D-004] No active Deluge download or seeding detected — may lack internet."
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# msg = "[D-004] Active Deluge traffic confirmed — VPN connectivity validated."
# logging.info(msg)
# send_discord_message("Check 4/4 successful.")

# D-004: External IP leak detection via RPC

send_discord_message("Executing check 4/4: Checking Deluge external IP...")

try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    deluge_ip_bytes = client.call("core.get_external_ip")
    deluge_ip = deluge_ip_bytes.decode() if isinstance(deluge_ip_bytes, bytes) else deluge_ip_bytes
except Exception as e:
    msg = "[D-004] Could not retrieve external IP from Deluge."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

host_ip = get_host_ip()
vpn_ip = get_vpn_tun_ip()

debug_msg = "\n".join([
    "[DEBUG] External IP Check:",
    f"Deluge IP: {deluge_ip}",
    f"VPN IP: {vpn_ip or 'Unavailable'}",
    f"Host IP: {host_ip or 'Unavailable'}"
])
send_discord_message(debug_msg)

if not deluge_ip or not host_ip:
    msg = "[D-004] External IP check failed — missing data."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

if deluge_ip == host_ip:
    msg = f"[D-004] Deluge IP matches host — traffic leak detected (Deluge: {deluge_ip}, Host: {host_ip})"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

msg = f"[D-004] Deluge external IP verified — VPN likely active (Deluge: {deluge_ip})"
logging.info(msg)
send_discord_message("Check 4/4 successful.")


# Done
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)