import os
import subprocess
from pathlib import Path

MODE = "Debug"
SCRIPT = "dummy_torrent_creator"

def debug(msg):
    if MODE == "Debug":
        print(f"[DEBUG - {SCRIPT}] {msg}")

# Resolve shared path relative to host project directory
dummy_dir = Path("shared").resolve()
dummy_file = dummy_dir / "vpn_seed_check_peer.txt"
torrent_file = dummy_dir / "dummy.torrent"

debug(f"Using shared directory: {dummy_dir}")
debug(f"Dummy file will be created at: {dummy_file}")
debug(f"Torrent file will be created at: {torrent_file}")

# Ensure shared directory exists
if not dummy_dir.exists():
    debug("Shared directory does not exist. Creating it.")
    dummy_dir.mkdir(parents=True, exist_ok=True)
else:
    debug("Shared directory already exists.")

# Create dummy file (256 KB)
with open(dummy_file, "wb") as f:
    f.write(os.urandom(256 * 1024))
debug(f"Created dummy file: {dummy_file} (256 KB)")

# Create .torrent using mktorrent
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
    debug(f"Successfully created torrent file at: {torrent_file}")
else:
    print("❌ ERROR creating torrent file")
    print(result.stderr)
