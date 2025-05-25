from deluge_client import DelugeRPCClient
import time
from pathlib import Path

MODE = "Debug"
SCRIPT = "deluge_vpn_download_test"

def debug(msg):
    if MODE == "Debug":
        print(f"[DEBUG - {SCRIPT}] {msg}")

# Connection settings
HOST = "localhost"
PORT = 58846
USERNAME = "deluge"
PASSWORD = "deluge"
TORRENT_PATH = "/shared/dummy.torrent"
TORRENT_NAME = "dummy.torrent"

# Connect to Deluge RPC
debug(f"Connecting to Deluge RPC at {HOST}:{PORT} as {USERNAME}")
client = DelugeRPCClient(HOST, PORT, USERNAME, PASSWORD)
client.connect()
debug("Connected.")

# Load .torrent file
torrent_data = Path(TORRENT_PATH).read_bytes()
debug(f"Read torrent file: {TORRENT_PATH} ({len(torrent_data)} bytes)")

# Add torrent
debug("Adding torrent to Deluge...")
torrent_id = client.call("core.add_torrent_file", TORRENT_NAME, torrent_data, {})
debug(f"Torrent added with ID: {torrent_id}")

# Wait for download
debug("Waiting 60 seconds for download...")
time.sleep(60)

# Check status
status = client.call("core.get_torrent_status", torrent_id, ["state", "progress"])
state = status[b"state"].decode()
progress = status[b"progress"]

debug(f"Torrent state: {state}")
debug(f"Torrent progress: {progress:.2f}%")

if state == "Seeding" or progress == 100.0:
    print("✅ DELUGE_CONFIRMED_DOWNLOADED")
else:
    print("❌ DELUGE_FAILED_TO_DOWNLOAD")
