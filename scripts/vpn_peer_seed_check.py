import libtorrent as lt
import os
import time
from pathlib import Path
import subprocess

MODE = "Debug"
SCRIPT = "vpn_peer_seed_check"

def debug(msg):
    if MODE == "Debug":
        print(f"[DEBUG - {SCRIPT}] {msg}")

def get_vpn_ip():
    try:
        result = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if "src" in parts:
                return parts[parts.index("src") + 1]
    except:
        return None

# Paths
temp = "/shared"
fpath = Path(temp) / "vpn_seed_check_peer.txt"
torrent_path = Path(temp) / "vpn_seed_check_peer.torrent"

# Create test file
with open(fpath, "wb") as f:
    f.write(os.urandom(256 * 1024))
debug(f"Created test file: {fpath}")

# Create torrent
fs = lt.file_storage()
lt.add_files(fs, str(fpath))
t = lt.create_torrent(fs)
t.add_tracker("udp://tracker.opentrackr.org:1337/announce")
t.set_creator("peer-test")
lt.set_piece_hashes(t, temp)
torrent = t.generate()

with open(torrent_path, "wb") as f:
    f.write(lt.bencode(torrent))
debug(f"Created torrent file: {torrent_path}")

# Bind to VPN IP
vpn_ip = get_vpn_ip()
if not vpn_ip:
    print("ERROR: VPN IP not found on tun0")
    exit(1)

ses = lt.session()
ses.apply_settings({
    'outgoing_interfaces': 'tun0',
    'listen_interfaces': f'{vpn_ip}:6881'
})
debug(f"Bound session to VPN IP: {vpn_ip}")

# Start torrent session
params = {
    'save_path': temp,
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    'ti': lt.torrent_info(str(torrent_path))
}
h = ses.add_torrent(params)
debug("Started torrent session as seeder...")

# Wait and monitor
time.sleep(60)
status = h.status()
debug(f"Torrent state: {status.state}")
debug(f"Upload rate: {status.upload_rate} B/s")
debug(f"Download rate: {status.download_rate} B/s")
debug(f"Total uploaded: {status.total_upload} bytes")
debug(f"Total downloaded: {status.total_download} bytes")
debug(f"Number of peers: {status.num_peers}")

if status.num_peers > 0 and status.upload_rate > 0:
    print("SEEDING_CONFIRMED")
else:
    print("SEEDING_FAILED")

# Cleanup
ses.remove_torrent(h)
try:
    fpath.unlink()
    torrent_path.unlink()
except:
    pass
