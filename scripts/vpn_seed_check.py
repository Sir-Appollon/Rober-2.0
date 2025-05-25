import libtorrent as lt
import os, time
from pathlib import Path

temp = "/tmp"
fpath = Path(temp) / "vpn_seed_check.txt"
with open(fpath, "wb") as f:
    f.write(os.urandom(256 * 1024))

fs = lt.file_storage()
lt.add_files(fs, str(fpath))
t = lt.create_torrent(fs)
t.add_tracker("udp://tracker.opentrackr.org:1337/announce")
t.set_creator("vpn-test")
lt.set_piece_hashes(t, temp)
torrent = t.generate()

torrent_path = Path(temp) / "vpn_seed_check.torrent"
with open(torrent_path, "wb") as f:
    f.write(lt.bencode(torrent))

ses = lt.session()
params = {
    'save_path': temp,
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    'ti': lt.torrent_info(torrent_path)
}
h = ses.add_torrent(params)

print("[DEBUG] Seeding started...")
time.sleep(40)

status = h.status()
if status.state == lt.torrent_status.seeding and status.total_upload > 0:
    print("SEEDING_SUCCESS")
else:
    print("SEEDING_FAILED")

# Cleanup
ses.remove_torrent(h)
try:
    fpath.unlink()
    torrent_path.unlink()
except:
    pass
