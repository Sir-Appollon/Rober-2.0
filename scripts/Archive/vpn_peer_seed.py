from pathlib import Path
import libtorrent as lt
import time
import os

# Define paths
TEMP_DIR = "/tmp"
TORRENT_PATH = Path(TEMP_DIR) / "vpn_seed_check.torrent"
DOWNLOAD_DIR = Path(TEMP_DIR) / "peer_download"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

print("[DEBUG] Starting peer client to test seeding...")

# Load .torrent
try:
    info = lt.torrent_info(str(TORRENT_PATH))
except Exception as e:
    print(f"[ERROR] Failed to load torrent: {e}")
    exit(1)

# Setup libtorrent session
ses = lt.session()
ses.listen_on(6881, 6891)
params = {
    'save_path': str(DOWNLOAD_DIR),
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    'ti': info
}
h = ses.add_torrent(params)
print(f"[DEBUG] Added torrent with infohash: {info.info_hash()}")

# Wait for activity
print("[DEBUG] Waiting to receive data from Deluge...")
success = False
for _ in range(60):
    s = h.status()
    if s.total_done > 0:
        print("[DEBUG] Torrent is receiving data.")
        success = True
        break
    time.sleep(1)

if success:
    print("PEER_RECEIVE_SUCCESS")
else:
    print("PEER_RECEIVE_FAILED")

# Cleanup
ses.remove_torrent(h)
try:
    if TORRENT_PATH.exists():
        TORRENT_PATH.unlink()
    for file in DOWNLOAD_DIR.glob("*"):
        file.unlink()
    DOWNLOAD_DIR.rmdir()
except Exception:
    pass
