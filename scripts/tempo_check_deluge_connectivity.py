# D-004: VPN-bound seeding validation using py3createtorrent

import tempfile
import time
import os
import subprocess
import re
from pathlib import Path
from deluge_client import DelugeRPCClient

send_discord_message("Executing check 4/4: Validating VPN seeding by Deluge using py3createtorrent...")

# Temporary test file/torrent paths
temp_dir = Path(tempfile.gettempdir())
test_file = temp_dir / "vpn_seed_check.bin"
torrent_file = temp_dir / "vpn_seed_check.torrent"

# Generate test file (512 KB)
with open(test_file, "wb") as f:
    f.write(os.urandom(512 * 1024))
send_discord_message(f"[DEBUG] Test file created at {test_file}")

# Create .torrent with py3createtorrent
try:
    result = subprocess.run(
        ["py3createtorrent", str(test_file), "-a", "udp://tracker.opentrackr.org:1337/announce"],
        capture_output=True,
        text=True,
        check=True
    )
    send_discord_message("[DEBUG] Torrent created using py3createtorrent.")
except subprocess.CalledProcessError as e:
    msg = "[D-004] Torrent creation failed."
    debug = f"[DEBUG] py3createtorrent stderr: {e.stderr.strip()}"
    logging.error(msg)
    logging.debug(debug)
    send_discord_message(msg)
    send_discord_message(debug)
    run_resolution("D-004")
    exit(4)

# Extract infohash from output (optional)
infohash_match = re.search(r"Infohash:\s+([a-f0-9]{40})", result.stdout)
torrent_infohash = infohash_match.group(1) if infohash_match else "N/A"
send_discord_message(f"[DEBUG] Infohash: {torrent_infohash}")

# Connect to Deluge and inject
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
except Exception:
    msg = "[D-004] Failed to connect to Deluge RPC."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Add torrent
torrent_id = None
try:
    with open(torrent_file, "rb") as tf:
        torrent_data = tf.read()
    torrent_id = client.call("core.add_torrent_file", torrent_file.name, torrent_data, {})
    send_discord_message(f"[DEBUG] Test torrent injected into Deluge with ID: {torrent_id}")
except Exception as e:
    msg = "[D-004] Failed to inject torrent into Deluge."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Wait 45 sec to monitor upload
time.sleep(45)

# Confirm upload
try:
    status = client.call("core.get_torrents_status", {}, ["name", "state", "total_uploaded"])
    match = next((k for k, v in status.items() if b"vpn_seed_check" in v[b"name"]), None)
    if match and status[match][b"state"] == b"Seeding" and status[match][b"total_uploaded"] > 0:
        msg = "[D-004] VPN-bound Deluge seeding confirmed — test successful."
        logging.info(msg)
        send_discord_message("Check 4/4 successful.")
    else:
        msg = "[D-004] Seeding failed — no upload detected."
        logging.error(msg)
        send_discord_message(msg)
        run_resolution("D-004")
        exit(4)
except Exception as e:
    msg = "[D-004] Failed to verify seeding."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Cleanup
try:
    if torrent_id:
        client.call("core.remove_torrent", torrent_id, True)
    test_file.unlink(missing_ok=True)
    torrent_file.unlink(missing_ok=True)
except:
    pass
