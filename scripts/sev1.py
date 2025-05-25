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


# Setup temporary test file
TEST_FILE = "/tmp/vpn_test.bin"
TORRENT_FILE = "/tmp/vpn_test.torrent"

# Setup temporary file paths
temp_dir = Path(tempfile.gettempdir())
test_file = temp_dir / "vpn_check.txt"
torrent_file = temp_dir / "vpn_check.torrent"

# Create the test file
with open(test_file, "wb") as f:
    f.write("This is a VPN connectivity test.")
    f.write(os.urandom(256 * 1024))  # 256 KB

# Create torrent
try:
    result = subprocess.run(
        [
            "mktorrent",
            "-a", "udp://tracker.openbittorrent.com:80/announce",
            "-o", str(torrent_file),
            str(test_file)
        ],
        capture_output=True,
        text=True,
        check=True
    )
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
except Exception as e:
    msg = "[D-004] Could not connect to Deluge RPC for torrent injection."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Add torrent to Deluge
torrent_id = None
try:
    with open(TORRENT_FILE, "rb") as f:
        torrent_data = f.read()
    torrent_id = client.call("core.add_torrent_file", "vpn_test.torrent", torrent_data, {})
except Exception as e:
    msg = "[D-004] Failed to inject test torrent into Deluge."
    logging.error(msg)
    send_discord_message(msg)
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
        logging.error(msg)
        send_discord_message(msg)
        run_resolution("D-004")
        exit(4)
except Exception as e:
    msg = "[D-004] Could not confirm torrent activity."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)
finally:
    try:
        if test:
            client.call("core.remove_torrent", test, True)
        os.remove(TEST_FILE)
        os.remove(TORRENT_FILE)
    except:
        pass

# Done
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)


logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)