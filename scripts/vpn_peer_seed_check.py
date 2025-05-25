import libtorrent as lt
import os
import time
from pathlib import Path
import subprocess

MODE = "Debug"  # Change to "Normal" for silent mode
SCRIPT = "vpn_peer_seed_check"

def debug(msg):
    if MODE == "Debug":
        print(f"[DEBUG - {SCRIPT}] {msg}")


def get_vpn_ip():
    try:
        result = subprocess.run(["ip", "addr", "show", "dev", "tun0"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except:
        return None

vpn_ip = get_vpn_ip()
if not vpn_ip:
    print("Failed to detect VPN IP")
    exit(1)

ses = lt.session()
ses.listen_on(6881, 6891)
ses.set_alert_mask(lt.alert.category_t.all_categories)
ses.apply_settings({
    'outgoing_interfaces': 'tun0',
    'listen_interfaces': f'{vpn_ip}:6881'
})

# Create temporary test file
temp = "/tmp"
fpath = Path(temp) / "vpn_seed_check_peer.txt"
with open(fpath, "wb") as f:
    f.write(os.urandom(256 * 1024))  # 256 KB
debug(f"Created test file: {fpath}")

# Create torrent
fs = lt.file_storage()
lt.add_files(fs, str(fpath))
t = lt.create_torrent(fs)
t.add_tracker("udp://tracker.opentrackr.org:1337/announce")
t.set_creator("peer-test")
lt.set_piece_hashes(t, temp)
torrent = t.generate()

torrent_path = Path(temp) / "vpn_seed_check_peer.torrent"
with open(torrent_path, "wb") as f:
    f.write(lt.bencode(torrent))
debug(f"Created torrent file: {torrent_path}")

# Start session
ses = lt.session()
params = {
    'save_path': temp,
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    'ti': lt.torrent_info(str(torrent_path))
}
h = ses.add_torrent(params)
debug("Started torrent session as peer...")

# Monitor activity
time.sleep(45)
status = h.status()
debug(f"Torrent state: {status.state}")
debug(f"Upload rate: {status.upload_rate} B/s")
debug(f"Download rate: {status.download_rate} B/s")
debug(f"Total uploaded: {status.total_upload} bytes")
debug(f"Total downloaded: {status.total_download} bytes")
debug(f"Number of peers: {status.num_peers}")

# Output result
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
