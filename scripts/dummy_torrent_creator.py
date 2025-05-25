import os
from pathlib import Path
import subprocess

MODE = "Debug"
SCRIPT = "dummy_torrent_creator"

def debug(msg):
    if MODE == "Debug":
        print(f"[DEBUG - {SCRIPT}] {msg}")

# Paths
dummy_dir = Path("/shared")
dummy_file = dummy_dir / "vpn_seed_check_peer.txt"
torrent_file = dummy_dir / "dummy.torrent"

# Create dummy file (256 KB)
with open(dummy_file, "wb") as f:
    f.write(os.urandom(256 * 1024))
debug(f"Created dummy file: {dummy_file}")

# Create .torrent using mktorrent
# Ensure mktorrent is installed in container: apt install -y mktorrent
tracker = "udp://tracker.opentrackr.org:1337/announce"
cmd = [
    "mktorrent",
    "-a", tracker,
    "-o", str(torrent_file),
    str(dummy_file)
]

debug(f"Running command: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode == 0:
    debug(f"Torrent created at: {torrent_file}")
else:
    print("ERROR creating torrent")
    print(result.stderr)
