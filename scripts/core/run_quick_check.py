# ===============================
# OLD CODE BLOCK — PRESERVED
# ===============================
# (Full code block previously written has been commented out for reference)
# [... entire previous implementation was here ...]

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
print("[DEBUG - run_quick_check.py] Testing CPU, RAM, Disk")
try:
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_usage = psutil.virtual_memory().percent
    disk_io = psutil.disk_io_counters()
    disk_read_MB = round(disk_io.read_bytes / (1024*1024), 2)
    disk_write_MB = round(disk_io.write_bytes / (1024*1024), 2)
    disk_usage = psutil.disk_usage("/").percent
    print(f"[DEBUG] CPU: {cpu_percent}%, RAM: {ram_usage}%, Disk: {disk_usage}%, Read: {disk_read_MB}MB, Write: {disk_write_MB}MB")
    test_pass.append("cpu_ram_disk")
except Exception as e:
    test_errors.append(f"cpu_ram_disk: {e}")

# Docker container status
print("[DEBUG - run_quick_check.py] Checking Docker containers")
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
print("[DEBUG - run_quick_check.py] Comparing VPN and Deluge IP")
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
    print(f"[DEBUG] Deluge IP: {deluge_ip}, VPN IP: {vpn_ip}")
    if deluge_ip != vpn_ip:
        critical_errors.append(f"Deluge IP ({deluge_ip}) != VPN IP ({vpn_ip})")
    else:
        test_pass.append("ip_match")
except Exception as e:
    test_errors.append(f"ip_compare: {e}")

# Deluge internet check
print("[DEBUG - run_quick_check.py] Checking Deluge internet access")
try:
    result = subprocess.run(["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        critical_errors.append("Deluge has no internet access (curl test failed)")
    else:
        test_pass.append("deluge_internet")
except Exception as e:
    test_errors.append(f"deluge_internet: {e}")

# Plex API Test
print("[DEBUG - run_quick_check.py] Connecting to Plex")
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    sessions = plex.sessions()
    info_lines = [f"[DEBUG] Plex Connected. Active sessions: {len(sessions)}"]
    for s in sessions:
        info_lines.append(f"User: {s.user.title}, Client: {s.player.title}, File: {s.title}, Transcode: {'Yes' if s.transcode else 'No'}")
        info_lines.append(f"Video: {getattr(s.media[0].parts[0].streams[0], 'codec', 'N/A')} | Audio: {getattr(s.media[0].parts[0].streams[1], 'codec', 'N/A')}")
        info_lines.append(f"Resolution: {getattr(s, 'videoResolution', 'Unknown')} | Duration: {getattr(s, 'viewOffset', 'N/A')}")

    # Plex process usage — temporarily commented due to syntax error issue
    # plex_proc = next((p for p in psutil.process_iter(['name']) if 'plex' in p.info['name'].lower()), None)
    # if plex_proc:
    #     try:
    #         cpu = plex_proc.cpu_percent(interval=1)
    #         mem = plex_proc.memory_info().rss / (1024 * 1024)
    #         free_space = psutil.disk_usage("/transcode").free / (1024 * 1024 * 1024) if os.path.exists("/transcode") else 'N/A'
    #         info_lines.append(f"Plex CPU: {cpu}% | RAM: {mem}MB | /transcode Free: {free_space}GB")
    #     except Exception as e:
    #         test_errors.append(f"plex_process: {e}")
    # else:
    #     test_errors.append("plex_process: Plex process not found")

    print("\n".join(info_lines))
    test_pass.append("plex")
except Exception as e:
    print(f"[DEBUG] Plex access failed: {e}")
    critical_errors.append(f"Plex access failure: {e}")

# Final report
if critical_errors:
    send_msg("[CRITICAL ERROR]\n" + "\n".join(critical_errors))
if test_errors:
    send_msg("[TEST ERROR]\n" + "\n".join(test_errors))
if mode == "debug" and not critical_errors and not test_errors:
    send_msg("[DEBUG MODE] All tests passed successfully")