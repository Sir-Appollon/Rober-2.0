import os
import subprocess
import logging
from dotenv import load_dotenv
import sys
from deluge_client import DelugeRPCClient
from pathlib import Path
import socket

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

def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
        s.close()
        return host_ip
    except:
        return None

def get_vpn_tun_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        return match.group(1) if match else None
    except:
        return None

def get_deluge_container_ip():
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", DELUGE_CONTAINER],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except:
        return None

vpn_ip = get_vpn_tun_ip()
deluge_ip = get_deluge_container_ip()
host_ip = get_host_ip()

if not vpn_ip or not deluge_ip or not host_ip:
    msg = "[D-004] IP check failed — unable to resolve all IPs"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

if vpn_ip == deluge_ip or vpn_ip == host_ip or deluge_ip == host_ip:
    msg = f"[D-004] Deluge leaking traffic — IP invalid or matched with host (VPN: {vpn_ip}, Deluge: {deluge_ip}, Host: {host_ip})"
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

msg = f"[D-004] Deluge bound correctly (VPN: {vpn_ip}, Deluge: {deluge_ip}, Host: {host_ip})"
logging.info(msg)
send_discord_message("Check 4/4 successful.")

logging.info(msg)
send_discord_message("Check 4/4 successful.")
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected. No further action required.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected. No further action required.")
exit(0)
