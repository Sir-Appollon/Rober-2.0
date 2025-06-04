import os
import sys
import subprocess
import logging
import time
import psutil
import shutil
import socket
from dotenv import load_dotenv
from plexapi.server import PlexServer
import importlib.util
import json
from datetime import datetime
from deluge_client import DelugeRPCClient
import re

start_time = time.time()
mode = "normal"
discord_connected = False

# Setup Discord integration

discord_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),
]

send_discord_message = None

for discord_path in discord_paths:
    if os.path.isfile(discord_path):
        try:
            spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
            discord_notify = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord_notify)
            send_discord_message = discord_notify.send_discord_message
            break
        except Exception as e:
            print(f"[DEBUG - DISCORD - Error] Failed to import module: {e}")

if not send_discord_message:
    print("[DEBUG - DISCORD - FAIL] Could not load Discord notifier module.")

# Function to get Deluge container IP
def get_deluge_ip():
    try:
        result = subprocess.run([
            "docker", "exec", "deluge", "ip", "addr", "show", "tun0"
        ], capture_output=True, text=True)
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[DEBUG - get_deluge_ip - tun0] {e}")

    try:
        result = subprocess.run([
            "docker", "exec", "deluge", "hostname", "-i"
        ], capture_output=True, text=True)
        ip = result.stdout.strip().split()[0]
        return ip
    except Exception as e:
        raise RuntimeError(f"[DEBUG - get_deluge_ip - fallback] Could not detect IP: {e}")

# Function to get VPN container IP
def get_vpn_ip():
    try:
        result = subprocess.run([
            "docker", "exec", "vpn", "ip", "addr", "show", "tun0"
        ], capture_output=True, text=True)
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[DEBUG - get_vpn_ip] {e}")
    raise RuntimeError("Could not detect VPN IP on tun0 inside container")

# Configure logging
logging.basicConfig(
    filename="/mnt/data/entry_log_quick_check.log",
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Function to append data to a JSON log file
def append_json_log(entry):
    LOG_FILE = "/mnt/data/system_monitor_log.json"
    entry["timestamp"] = datetime.now().isoformat()

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump([entry], f, indent=2)
    else:
        with open(LOG_FILE, "r+") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
            logs.append(entry)
            f.seek(0)
            json.dump(logs, f, indent=2)
            f.truncate()

# Load environment variables
load_dotenv("/app/.env")

# Simplified Deluge stats (no downloading/seeding metrics)
deluge_stats = {}

try:
    deluge_client = DelugeRPCClient("127.0.0.1", 58846, "localclient", os.getenv("DELUGE_PASSWORD"))
    deluge_client.connect()
    torrents = deluge_client.call(
        "core.get_torrents_status",
        {},
        ["name", "state", "download_payload_rate", "upload_payload_rate"]
    )
except Exception as e:
    print(f"[DEBUG - DELUGE - Error] {e}")

# Collect disk usage only for specific mount points
custom_mounts = ["/", "/mnt/media", "/mnt/media/extra"]
disk_status = {}

for mount in custom_mounts:
    try:
        usage = shutil.disk_usage(mount)
        disk_status[mount] = {
            "total_gb": round(usage.total / (1024**3)),
            "used_pct": round((usage.used / usage.total) * 100)
        }
    except Exception as e:
        print(f"[DEBUG - STORAGE - Error] {mount}: {e}")

# Assemble system metrics for JSON output
try:
    data_entry = {
        "docker_services": {
            service: subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", service], capture_output=True, text=True).stdout.strip() == "true"
            for service in ["plex-server", "vpn", "deluge"]
        },
        "network": {
            "vpn_ip": [],
            "deluge_ip": [],
            "internet_access": False,
            "speedtest": {
                "download_mbps": 0.0,
                "upload_mbps": 0.0
            }
        },
        "plex": {
            "connected": False,
            "active_sessions": 0,
            "unique_clients": 0,
            "transcoding_sessions": 0,
            "cpu_usage": 0.0,
            "ram_usage": 0.0,
            "transcode_folder_found": False,
            "local_access": True,
            "external_access": "unknown"
        },
        "system": {
            "cpu_total": 0.0,
            "ram_total": 0.0,
            "cpu_temp_c": 0.0,
            "internet_io": {
                "sent_mb": 0.0,
                "received_mb": 0.0
            },
            "disk_io": {
                "read_mb": 0.0,
                "write_mb": 0.0
            }
        },
        "performance": {
            "runtime_seconds": 0.0
        },
        "deluge": deluge_stats,
        "storage": disk_status
    }

    append_json_log(data_entry)

except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")
