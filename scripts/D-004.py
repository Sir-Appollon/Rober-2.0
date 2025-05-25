import libtorrent as lt
import os, time, json, re
from pathlib import Path
import subprocess

# Setup paths
temp = "/tmp"
fpath = Path(temp) / "vpn_seed_check.txt"
torrent_path = Path(temp) / "vpn_seed_check.torrent"
core_conf_path = "/config/core.conf"

# Create test file
with open(fpath, "wb") as f:
    f.write(os.urandom(256 * 1024))
print(f"[DEBUG] Created test file: {fpath}")

# Create torrent
fs = lt.file_storage()
lt.add_files(fs, str(fpath))
t = lt.create_torrent(fs)
t.add_tracker("udp://tracker.opentrackr.org:1337/announce")
t.set_creator("vpn-test")
lt.set_piece_hashes(t, temp)
torrent = t.generate()

with open(torrent_path, "wb") as f:
    f.write(lt.bencode(torrent))
print(f"[DEBUG] Created torrent file: {torrent_path}")

# Copy torrent file to peer watch folder
Path("/mnt/data/seedcheck/").mkdir(parents=True, exist_ok=True)
subprocess.run(["cp", str(torrent_path), "/mnt/data/seedcheck/vpn_seed_check.torrent"])


# Load configured IP from core.conf (manual parse for Deluge syntax)
outgoing_ip = None
try:
    with open(core_conf_path, "r") as conf:
        for line in conf:
            if '"outgoing_interface"' in line:
                match = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', line)
                if match:
                    outgoing_ip = match.group(1)
                    break
    print(f"[DEBUG] Outgoing IP in core.conf: {outgoing_ip or 'Not found'}")
except Exception as e:
    print(f"[DEBUG] Failed to parse core.conf: {e}")


# Get VPN IP
try:
    result = subprocess.run(
        ["ip", "addr", "show", "tun0"],
        capture_output=True,
        text=True
    )
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
    vpn_ip = match.group(1) if match else None
    print(f"[DEBUG] VPN IP (tun0): {vpn_ip}")
except Exception as e:
    print(f"[DEBUG] Failed to get VPN IP: {e}")
    vpn_ip = None

# Compare IPs
if outgoing_ip and vpn_ip:
    print(f"[DEBUG] Is Deluge IP matching VPN IP? {'YES' if outgoing_ip == vpn_ip else 'NO'}")

# Start seeding
ses = lt.session()
params = {
    'save_path': temp,
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    'ti': lt.torrent_info(str(torrent_path))
}
h = ses.add_torrent(params)
print("[DEBUG] Seeding started...")
time.sleep(45)  # Allow some time for connections

status = h.status()

print(f"[DEBUG] Torrent state: {status.state}")
print(f"[DEBUG] Upload rate: {status.upload_rate} B/s")
print(f"[DEBUG] Download rate: {status.download_rate} B/s")
print(f"[DEBUG] Total uploaded: {status.all_time_upload} bytes")
print(f"[DEBUG] Total downloaded: {status.all_time_download} bytes")
print(f"[DEBUG] Number of peers: {status.num_peers}")

if status.state == lt.torrent_status.seeding and status.all_time_upload > 0:
    print("SEEDING_STATE_CONFIRMED")
else:
    print("SEEDING_STATE_FAILED")


if status.state == lt.torrent_status.seeding and status.all_time_upload > 0:
    print("SEEDING_STATE_CONFIRMED")
else:
    print("SEEDING_STATE_FAILED")


# Cleanup
ses.remove_torrent(h)
try:
    fpath.unlink()
    torrent_path.unlink()
except:
    pass
