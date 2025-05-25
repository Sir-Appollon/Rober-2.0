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

# D-004: VPN-bound seeding capability check via temporary torrent

send_discord_message("Executing check 4/4: Verifying VPN-bound Deluge seeding capability...")

import time
import random
import string
import tempfile

# Setup temporary file paths
temp_dir = Path(tempfile.gettempdir())
test_file = temp_dir / "vpn_check.txt"
torrent_file = temp_dir / "vpn_check.torrent"

# Create the test file
try:
    with open(test_file, "wb") as f:
        f.write("This is a VPN connectivity test.".encode())
        f.write(os.urandom(256 * 1024))  # 256 KB
    debugf = f"[DEBUG] Created test file at {test_file}"
    logging.debug(debugf)
    send_discord_message(debugf)
except Exception as e:
    msg = "[D-004] Failed to create temporary test file."
    debugf = f"[DEBUG] {e}"
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)

# Create torrent
try:
    result = subprocess.run([
    "docker", "run", "--rm",
    "-v", f"{test_file.parent}:/data",
    "crazymax/mktorrent",
    "-a", "dht://",
    "-o", f"/data/{torrent_file.name}",
    f"/data/{test_file.name}"
], capture_output=True, text=True, check=True)

    debugf = f"[DEBUG] Torrent created: {torrent_file}"
    logging.debug(debugf)
    send_discord_message(debugf)

except subprocess.CalledProcessError as e:
    msg = "[D-004] Failed to create torrent for VPN test."
    debugf = f"[DEBUG] mktorrent stderr: {e.stderr.strip()}"
    logging.error(msg)
    logging.debug(debugf)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)

# Connect to Deluge
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    send_discord_message("[DEBUG] Connected to Deluge RPC.")
except Exception as e:
    msg = "[D-004] Could not connect to Deluge RPC for torrent injection."
    debugf = f"[DEBUG] {e}"
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)

# Add torrent to Deluge
torrent_id = None
try:
    with open(torrent_file, "rb") as f:
        torrent_data = f.read()
    torrent_id = client.call("core.add_torrent_file", "vpn_test.torrent", torrent_data, {})
    debugf = f"[DEBUG] Test torrent added to Deluge: {torrent_id}"
    logging.debug(debugf)
    send_discord_message(debugf)
except Exception as e:
    msg = "[D-004] Failed to inject test torrent into Deluge."
    debugf = f"[DEBUG] {e}"
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)

# Wait for upload activity
time.sleep(45)
try:
    status = client.call("core.get_torrents_status", {}, ["name", "state", "total_uploaded"])
    test = next((k for k, v in status.items() if b"vpn_test" in v[b"name"]), None)

    if test and status[test][b"state"] == b"Seeding" and status[test][b"total_uploaded"] > 0:
        msg = "[D-004] Deluge confirmed to seed via VPN — validated."
        logging.info(msg)
        send_discord_message("Check 4/4 successful.")
    else:
        msg = "[D-004] Deluge seeding test failed — torrent did not upload."
        debugf = f"[DEBUG] Torrent state: {status[test][b'state']}, Uploaded: {status[test][b'total_uploaded']}"
        logging.error(msg)
        send_discord_message(msg)
        send_discord_message(debugf)
        run_resolution("D-004")
        exit(4)
except Exception as e:
    msg = "[D-004] Could not confirm torrent activity."
    debugf = f"[DEBUG] {e}"
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)

# Cleanup
try:
    if torrent_id:
        client.call("core.remove_torrent", torrent_id, True)
    os.remove(test_file)
    os.remove(torrent_file)
    send_discord_message("[DEBUG] Cleanup successful.")
except Exception as e:
    send_discord_message(f"[DEBUG] Cleanup failed: {e}")


# Done
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)