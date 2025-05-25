import os
import sys
import re  # Required for regex matching
import socket
import subprocess
import logging
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from pathlib import Path
import tempfile
import socket
import time


def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return None

def get_vpn_tun_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        return match.group(1) if match else None
    except:
        return None


# Setup import path for shared modules
sys.path.append("..")
from discord_notify import send_discord_message

# Setup logging
log_file = "/mnt/data/sev1_diagnostic.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load environment from known paths
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        break

# Environment and container names
VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"
DELUGE_USER = "localclient"
DELUGE_PASS = os.getenv("DELUGE_PASSWORD")

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

# D-001: VPN container check
send_discord_message("Executing check 1/4: Verifying VPN container status...")
if not container_running(VPN_CONTAINER):
    msg = "[D-001] VPN container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-001")
    exit(1)
send_discord_message("Check 1/4 successful.")

# D-002: Deluge container check
send_discord_message("Executing check 2/4: Verifying Deluge container status...")
if not container_running(DELUGE_CONTAINER):
    msg = "[D-002] Deluge container is down — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-002")
    exit(2)
send_discord_message("Check 2/4 successful.")

# D-003: Deluge RPC check
send_discord_message("Executing check 3/4: Testing Deluge RPC connection...")
def deluge_rpc_accessible():
    try:
        client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
        client.connect()
        return True
    except:
        return False

if not deluge_rpc_accessible():
    msg = "[D-003] Deluge RPC error — problem found, attempting resolution."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-003")
    exit(3)
send_discord_message("Check 3/4 successful.")

# # D-004: Deluge activity confirmation

# send_discord_message("Executing check 4/4: Verifying active Deluge download or seeding...")

# try:
#     client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
#     client.connect()
#     torrents = client.call("core.get_torrents_status", {}, ["state"])
#     active = any(t[b"state"] in [b"Downloading", b"Seeding"] for t in torrents.values())
# except Exception as e:
#     msg = "[D-004] Deluge RPC access failed during activity check."
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# if not active:
#     msg = "[D-004] No active Deluge download or seeding detected — may lack internet."
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# msg = "[D-004] Active Deluge traffic confirmed — VPN connectivity validated."
# logging.info(msg)
# send_discord_message("Check 4/4 successful.")

# # D-004: External IP leak detection via RPC and Internet access check

# send_discord_message("Executing check 4/4: Verifying Deluge connectivity and external IP security...")

# def deluge_has_internet():
#     try:
#         result = subprocess.run(
#             ["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"],
#             stdout=subprocess.DEVNULL,
#             stderr=subprocess.DEVNULL
#         )
#         return result.returncode == 0
#     except Exception as e:
#         logging.error(f"[D-004] Internet test via Deluge failed: {e}")
#         return False

# def get_host_ip():
#     try:
#         s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         s.connect(("8.8.8.8", 80))
#         ip = s.getsockname()[0]
#         s.close()
#         return ip
#     except:
#         return None

# def get_vpn_tun_ip():
#     try:
#         result = subprocess.run(
#             ["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "tun0"],
#             capture_output=True, text=True
#         )
#         match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
#         return match.group(1) if match else None
#     except:
#         return None

# def get_deluge_rpc_ip():
#     try:
#         client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
#         client.connect()
#         status = client.call("core.get_external_ip")
#         return status
#     except:
#         return None

# host_ip = get_host_ip()
# vpn_ip = get_vpn_tun_ip()
# deluge_ip = get_deluge_rpc_ip()

# debug_message = "\n".join([
#     "[DEBUG] IP Resolution Snapshot:",
#     f"Host IP: {host_ip or 'Unavailable'}",
#     f"VPN IP: {vpn_ip or 'Unavailable'}",
#     f"Deluge IP: {deluge_ip or 'Unavailable'}"
# ])
# send_discord_message(debug_message)

# if not deluge_ip or not vpn_ip or not host_ip:
#     msg = "[D-004] IP check failed — could not resolve all IPs"
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# if deluge_ip == host_ip:
#     msg = f"[D-004] Deluge leaking — external IP matches host (Deluge: {deluge_ip})"
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)

# def deluge_has_internet():
#     try:
#         result = subprocess.run(
#             ["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://google.com"],
#             capture_output=True,
#             text=True
#         )
#         return result.returncode == 0
#     except:
#         return False

# if not deluge_has_internet():
#     msg = "[D-004] Deluge container has no internet access."
#     logging.error(msg)
#     send_discord_message(msg)
#     run_resolution("D-004")
#     exit(4)
# else:
#     send_discord_message("[DEBUG] Deluge container has internet access.")

# msg = f"[D-004] Deluge confirmed behind VPN and has internet access (Deluge IP: {deluge_ip})"
# logging.info(msg)
# send_discord_message("Check 4/4 successful.")

# D-004: VPN-bound seeding validation using py3createtorrent
send_discord_message("Executing check 4/4: Validating VPN seeding by Deluge using py3createtorrent...")

import tempfile
import time

# Paths
TRACKER = "udp://tracker.opentrackr.org:1337/announce"
temp_dir = Path(tempfile.gettempdir())
test_file = temp_dir / "vpn_seed_check.bin"
torrent_file = temp_dir / f"{test_file.name}.torrent"

# Create test file
with open(test_file, "wb") as f:
    f.write(os.urandom(256 * 1024))  # 256 KB

logging.debug(f"[DEBUG] Test file created at {test_file}")
send_discord_message(f"[DEBUG] Test file created at {test_file}")

# Run py3createtorrent in temp dir
original_cwd = os.getcwd()
os.chdir(temp_dir)
try:
    result = subprocess.run([
        "py3createtorrent", str(test_file),
        "-t", TRACKER
    ], capture_output=True, text=True, check=True)
    logging.debug("[DEBUG] Torrent created using py3createtorrent.")
    send_discord_message("[DEBUG] Torrent created using py3createtorrent.")
except subprocess.CalledProcessError as e:
    msg = "[D-004] Torrent creation failed."
    debugf = f"[DEBUG] py3createtorrent stderr: {e.stderr.strip()}"
    logging.error(msg)
    logging.debug(debugf)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    os.chdir(original_cwd)
    exit(4)
os.chdir(original_cwd)

# Verify torrent exists
if not torrent_file.exists():
    msg = "[D-004] Torrent file not found after creation."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Connect to Deluge
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
except Exception as e:
    msg = "[D-004] Could not connect to Deluge RPC for torrent injection."
    logging.error(msg)
    send_discord_message(msg)
    run_resolution("D-004")
    exit(4)

# Ensure a fresh connection for injection
try:
    client = DelugeRPCClient("localhost", 58846, DELUGE_USER, DELUGE_PASS, False)
    client.connect()
    with open(torrent_file, "rb") as f:
        torrent_data = f.read()
    torrent_id = client.call("core.add_torrent_file", "vpn_seed_check.torrent", torrent_data, {})
except Exception as e:
    msg = "[D-004] Failed to inject torrent into Deluge."
    debugf = f"[DEBUG] Injection error type: {type(e).__name__}, detail: {repr(e)}"
    logging.error(msg)
    logging.debug(debugf)
    send_discord_message(msg)
    send_discord_message(debugf)
    run_resolution("D-004")
    exit(4)




# Wait and confirm upload
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
except Exception:
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


# Done
send_discord_message("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
logging.info("SEV 1 diagnostic complete — all tests passed or non-critical warnings detected.")
exit(0)