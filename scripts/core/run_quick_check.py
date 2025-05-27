# ===============================
# OLD CODE BLOCK — PRESERVED
# ===============================
# (Full code block previously written has been commented out for reference)
# [... entire previous implementation was here ...]
# see end
# ===============================
# UPDATED FULL TESTING VERSION
# ===============================
import os
import sys
import subprocess
import logging
import json
import time
import re
import psutil
from datetime import datetime
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import importlib.util

mode = "debug"
start_time = time.time()

print("[DEBUG - run_quick_check.py] Script initiated")

# Setup Discord
discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

def send_msg(msg):
    try:
        send_discord_message(msg)
        return True
    except Exception as e:
        print(f"[DEBUG - run_quick_check.py] Discord message failed: {e}")
        return False

# Logging
log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(message)s")

# Load .env
print("[DEBUG - run_quick_check.py] Attempting to load .env")
env_loaded = False
for p in [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]:
    if load_dotenv(p):
        print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
        env_loaded = True
        break
if not env_loaded:
    print("[DEBUG - run_quick_check.py] No .env file found.")

# Configuration
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
DELUGE_PASSWORD = os.getenv("DELUGE_PASSWORD")
containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]

# Test results
critical_errors = []
test_errors = []
test_pass = []

# CPU, RAM, Disk, Network
try:
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_usage = psutil.virtual_memory().percent
    disk_io = psutil.disk_io_counters()
    disk_read_MB = round(disk_io.read_bytes / (1024*1024), 2)
    disk_write_MB = round(disk_io.write_bytes / (1024*1024), 2)
    disk_usage = psutil.disk_usage("/").percent
    test_pass.append("cpu_ram_disk")
except Exception as e:
    test_errors.append(f"cpu_ram_disk: {e}")

# Docker container status
try:
    down = []
    for c in containers:
        status = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", c], capture_output=True, text=True)
        if status.stdout.strip() != "true":
            down.append(c)
    if down:
        critical_errors.append(f"Containers down: {', '.join(down)}")
    else:
        test_pass.append("containers")
except Exception as e:
    test_errors.append(f"docker_check: {e}")

# VPN IP and Deluge IP
deluge_ip, vpn_ip = None, None
try:
    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "deluge", "core.conf"))) as f:
        for line in f:
            if '"outgoing_interface"' in line:
                match = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', line)
                if match:
                    deluge_ip = match.group(1)
    result = subprocess.run(["docker", "exec", "vpn", "ip", "addr", "show", "tun0"], capture_output=True, text=True)
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
    vpn_ip = match.group(1) if match else None
    if deluge_ip != vpn_ip:
        critical_errors.append(f"Deluge IP ({deluge_ip}) != VPN IP ({vpn_ip})")
    else:
        test_pass.append("ip_match")
except Exception as e:
    test_errors.append(f"ip_compare: {e}")

# Deluge internet check
try:
    result = subprocess.run(["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        critical_errors.append("Deluge has no internet access (curl test failed)")
    else:
        test_pass.append("deluge_internet")
except Exception as e:
    test_errors.append(f"deluge_internet: {e}")

# Plex API Test
try:
    print("[DEBUG - run_quick_check.py] Connecting to Plex")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    sessions = plex.sessions()
    info_lines = [f"[DEBUG] Plex Connected. Active sessions: {len(sessions)}"]
    for s in sessions:
        info_lines.append(f"User: {s.user.title}, Client: {s.player.title}, File: {s.title}, Transcode: {'Yes' if s.transcode else 'No'}")
        info_lines.append(f"Video: {getattr(s.media[0].parts[0].streams[0], 'codec', 'N/A')} | Audio: {getattr(s.media[0].parts[0].streams[1], 'codec', 'N/A')}")
        info_lines.append(f"Resolution: {getattr(s, 'videoResolution', 'Unknown')} | Duration: {getattr(s, 'viewOffset', 'N/A')}")

    # Plex process usage
    plex_proc = next((p for p in psutil.process_iter(['name']) if 'plex' in p.info['name'].lower()), None)
    cpu = plex_proc.cpu_percent(interval=1) if plex_proc else 'N/A'
    mem = plex_proc.memory_info().rss / (1024 * 1024) if plex_proc else 'N/A'
    free_space = psutil.disk_usage("/transcode").free / (1024 * 1024 * 1024) if os.path.exists("/transcode") else 'N/A'
    info_lines.append(f"Plex CPU: {cpu}% | RAM: {mem}MB | /transcode Free: {free_space}GB")
    print("\n".join(info_lines))
    test_pass.append("plex")
except Exception as e:
    critical_errors.append(f"Plex access failure: {e}")

# Final report
if critical_errors:
    send_msg("[CRITICAL ERROR]\n" + "\n".join(critical_errors))
if test_errors:
    send_msg("[TEST ERROR]\n" + "\n".join(test_errors))
if mode == "debug" and not critical_errors and not test_errors:
    send_msg("[DEBUG MODE] All tests passed successfully")


# import os
# import sys
# import subprocess
# import logging
# import json
# import time
# import re
# import psutil
# from dotenv import load_dotenv
# from deluge_client import DelugeRPCClient
# from plexapi.server import PlexServer
# import importlib.util

# mode = "debug"
# start_time = time.time()

# # Discord setup
# discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
# spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
# discord_notify = importlib.util.module_from_spec(spec)
# spec.loader.exec_module(discord_notify)
# send_discord_message = discord_notify.send_discord_message

# # Logging
# log_file = "/mnt/data/entry_log_quick_check.log"
# logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(message)s")

# # Load env
# env_paths = [
#     os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
#     os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
# ]
# for p in env_paths:
#     if load_dotenv(p):
#         if mode == "debug":
#             print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
#         break

# # Configs
# deluge_config = {
#     "host": "localhost",
#     "port": 58846,
#     "username": "localclient",
#     "password": os.getenv("DELUGE_PASSWORD"),
# }
# plex_config = {
#     "url": os.getenv("PLEX_SERVER"),
#     "token": os.getenv("PLEX_TOKEN"),
# }
# containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]

# # Docker availability

# def docker_available():
#     try:
#         subprocess.check_output(["docker", "ps"], stderr=subprocess.DEVNULL)
#         return True
#     except:
#         return False

# def check_container(name):
#     if not docker_available():
#         logging.warning("Docker not available — skipping container check.")
#         return False
#     try:
#         result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
#         return result.stdout.strip() == "true"
#     except:
#         return False

# # Plex monitoring

# def check_plex_local():
#     print("[DEBUG] Starting Plex test")
#     try:
#         print(f"[DEBUG] Connecting to Plex server at {plex_config['url']}")
#         server = PlexServer(plex_config["url"], plex_config["token"])
#         sessions = server.sessions()
#         info_lines = []
#         for session in sessions:
#             media = session.media[0].parts[0].streams
#             video_stream = next((s for s in media if s.streamType == 1), None)
#             audio_stream = next((s for s in media if s.streamType == 2), None)
#             resolution = getattr(session, 'videoResolution', 'Unknown')
#             transcode = getattr(session, 'transcode', None)
#             transcode_status = 'Yes' if transcode else 'No'
#             info_lines.append(f"User: {session.user.title}, Client: {session.player.title}, File: {session.title}, Video: {video_stream.codec if video_stream else 'N/A'}, {resolution}, Audio: {audio_stream.codec if audio_stream else 'N/A'}, Transcode: {transcode_status}")

#         plex_proc = next((p for p in psutil.process_iter(['name']) if 'plex' in p.info['name'].lower()), None)
#         cpu = plex_proc.cpu_percent(interval=1) if plex_proc else 'N/A'
#         mem = plex_proc.memory_info().rss / (1024 * 1024) if plex_proc else 'N/A'
#         temp_dir = "/transcode"
#         free_space = psutil.disk_usage(temp_dir).free / (1024 * 1024 * 1024) if os.path.exists(temp_dir) else 'N/A'

#         info_lines.append(f"CPU: {cpu}% | RAM: {mem}MB | Temp FS Free: {free_space}GB")
#         info_lines.append(f"Clients: {len(sessions)}")
#         send_discord_message("\n".join(info_lines))
#         return True
#     except Exception as e:
#         print(f"[DEBUG] Plex connection failed: {e}")
#         return False

# # Run all checks

# def run_all_checks():
#     print("[DEBUG] Starting Deluge and network tests")
#     results = {
#         "plex": check_plex_local(),
#         "deluge_active": False,
#         "deluge_ip_match": False,
#         "radarr_sonarr": False,
#         "all_containers": False
#     }

#     try:
#         client = DelugeRPCClient(**deluge_config, decode_utf8=False)
#         client.connect()
#         torrents = client.call("core.get_torrents_status", {}, ["state"])
#         results["deluge_active"] = any(t[b"state"] in (b"Downloading", b"Seeding") for t in torrents.values())
#         print(f"[DEBUG] Deluge active: {results['deluge_active']}")
#     except Exception as e:
#         print(f"[DEBUG] Deluge check failed: {e}")

#     deluge_ip, vpn_ip, has_net = None, None, False
#     try:
#         path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "deluge", "core.conf"))
#         with open(path, "r") as f:
#             for line in f:
#                 if '"outgoing_interface"' in line:
#                     match = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', line)
#                     deluge_ip = match.group(1)
#                     break
#         print(f"[DEBUG] Deluge config IP: {deluge_ip}")
#     except Exception as e:
#         print(f"[DEBUG] Failed to read Deluge config: {e}")

#     try:
#         result = subprocess.run(["docker", "exec", "vpn", "ip", "addr", "show", "tun0"], capture_output=True, text=True)
#         match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
#         vpn_ip = match.group(1) if match else None
#         print(f"[DEBUG] VPN IP: {vpn_ip}")
#     except Exception as e:
#         print(f"[DEBUG] Failed to get VPN IP: {e}")

#     try:
#         result = subprocess.run(["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"],
#                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#         has_net = result.returncode == 0
#         print(f"[DEBUG] Deluge internet access: {has_net}")
#     except Exception as e:
#         print(f"[DEBUG] Deluge internet check failed: {e}")

#     results["deluge_ip_match"] = deluge_ip and vpn_ip and deluge_ip == vpn_ip and has_net
#     print("[DEBUG] Starting Radarr/Sonarr/container checks")
#     results["radarr_sonarr"] = check_container("radarr") and check_container("sonarr")
#     results["all_containers"] = all(check_container(c) for c in containers)

#     return results

# # Execute and report
# print("[DEBUG] Running full check suite")
# status = run_all_checks()
# failures = [k for k, v in status.items() if not v]

# if not status.get("plex"):
#     logging.info("SEV 0: Plex not responding locally.")
#     send_discord_message("[SEV 0] Plex access failure detected.")
# if not status.get("deluge_active"):
#     logging.info("SEV 1: Deluge not active.")
#     send_discord_message("[SEV 1] Deluge idle — diagnostic triggered.")
# if not status.get("deluge_ip_match"):
#     logging.info("SEV 1: Deluge VPN/IP/Net mismatch.")
#     send_discord_message("[SEV 1] Deluge IP mismatch or no internet.")
# if not status.get("radarr_sonarr"):
#     logging.info("SEV 2: Radarr or Sonarr not responding.")
#     send_discord_message("[SEV 2] Radarr/Sonarr failure.")
# if not status.get("all_containers"):
#     logging.info("SEV 3: One or more containers down.")
#     send_discord_message("[SEV 3] Container failure.")

# if failures:
#     send_discord_message(f"[INFO] Some checks failed: {', '.join(failures)}")
# else:
#     duration = round(time.time() - start_time, 2)
#     send_discord_message(f"[OK] All services operational. Runtime: {duration}s")


