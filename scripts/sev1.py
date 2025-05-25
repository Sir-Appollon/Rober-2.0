import os
import sys
import re
import time
import socket
import logging
import subprocess
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from pathlib import Path
import tempfile

# Path setup
sys.path.append("..")
from discord_notify import send_discord_message

# Logging
log_file = "/mnt/data/sev1_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        break

# Constants
VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"
DELUGE_USER = "localclient"
DELUGE_PASS = os.getenv("DELUGE_PASSWORD")
TRACKER = "udp://tracker.opentrackr.org:1337/announce"

# Notify start
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
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
except:
    msg = "[D-003] Deluge RPC error — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-003")
    exit(3)
send_discord_message("Check 3/4 successful.")

# D-004
send_discord_message("Executing check 4/4: Validating VPN seeding by Deluge using py3createtorrent...")

temp_dir = Path(tempfile.gettempdir())
test_file = temp_dir / "vpn_seed_check.bin"
torrent_file = temp_dir / f"{test_file.name}.torrent"

with open(test_file, "wb") as f:
    f.write(os.urandom(256 * 1024))

logging.debug(f"[DEBUG] Test file created at {test_file}")
send_discord_message(f"[DEBUG] Test file created at {test_file}")

# Generate torrent
os.chdir(temp_dir)
try:
    subprocess.run([
        "py3createtorrent", str(test_file), "-t", TRACKER
    ], capture_output=True, text=True, check=True)
    send_discord_message("[DEBUG] Torrent created using py3createtorrent.")
except subprocess.CalledProcessError as e:
    msg = "[D-004] Torrent creation failed."
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(f"[DEBUG] py3createtorrent stderr: {e.stderr.strip()}")
    run_resolution("D-004")
    os.chdir(Path(__file__).parent)
    exit(4)
os.chdir(Path(__file__).parent)

# Confirm torrent file exists
if not torrent_file.exists():
    msg = "[D-004] Torrent file not found after creation."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Inject into Deluge
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    with open(torrent_file, "rb") as f:
        torrent_data = f.read()
    torrent_id = client.call("core.add_torrent_file", "vpn_seed_check.torrent", torrent_data, {})
except Exception as e:
    msg = "[D-004] Failed to inject torrent into Deluge."
    logging.error(msg)
    send_discord_message(msg)
    send_discord_message(f"[DEBUG] Injection error type: {type(e).__name__}, detail: {repr(e)}")
    run_resolution("D-004")
    exit(4)

# Monitor seeding
time.sleep(45)
try:
    status = client.call("core.get_torrents_status", {}, ["name", "state", "total_uploaded"])
    match = next((k for k, v in status.items() if b"vpn_seed_check" in v[b"name"]), None)
    if match and status[match][b"state"] == b"Seeding" and status[match][b"total_uploaded"] > 0:
        msg = "[D-004] Deluge confirmed seeding via VPN — validated."
        logging.info(msg)
        send_discord_message("Check 4/4 successful.")
    else:
        msg = "[D-004] Seeding test failed — torrent did not upload."
        logging.error(msg)
        send_discord_message(msg)
        run_resolution("D-004")
        exit(4)
except:
    msg = "[D-004] Could not confirm torrent activity."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Cleanup
try:
    if match:
        client.call("core.remove_torrent", match, True)
    test_file.unlink(missing_ok=True)
    torrent_file.unlink(missing_ok=True)
except:
    pass

send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)
