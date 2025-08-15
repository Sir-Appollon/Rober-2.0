#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import logging
import time
import psutil
import shutil
from dotenv import load_dotenv
from plexapi.server import PlexServer
import importlib.util
import json
from datetime import datetime
from deluge_client import DelugeRPCClient
import re
import socket
import multiprocessing

# ========= CONFIG DE BASE =========
core_count = multiprocessing.cpu_count()
start_time = time.time()
mode = "debug"

print("[DEBUG - run_quick_check.py - INIT - 1] Script initiated")

# Charger .env
print("[DEBUG - run_quick_check.py - ENV - 1] Attempting to load /app/.env")
if load_dotenv("/app/.env"):
    print("[DEBUG - run_quick_check.py - ENV - 2] Loaded /app/.env")
    env_loaded = True
else:
    print("[DEBUG - run_quick_check.py - ENV - 3] No .env file found.")
    env_loaded = False

# ========= CONFIG DELUGE RPC =========
deluge_config = {
    "host": "localhost",
    "port": 58846,
    "username": "localclient",
    "password": "e0db9d7d51b2c62b7987031174607aa822f94bc9",
}

# ========= LOGGING FICHIER =========
logging.basicConfig(
    filename="/mnt/data/entry_log_quick_check.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

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

# ========= DISCORD (OPTIONNEL) =========
print("[DEBUG - run_quick_check.py - INIT - 2] Initializing Discord connection")
discord_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),
]

send_discord_message = None
for discord_path in discord_paths:
    if os.path.isfile(discord_path):
        print(f"[DEBUG] Using Discord notify at: {discord_path}")
        try:
            spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
            discord_notify = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord_notify)
            send_discord_message = discord_notify.send_discord_message
            break
        except Exception as e:
            print(f"[DEBUG] Failed to import discord_notify: {e}")

# ========= UTIL NET =========
def _ensure_https(domain: str) -> str:
    if not domain:
        return ""
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"

def _extract_host(domain_url: str) -> str:
    return re.sub(r"^https?://", "", domain_url).split("/", 1)[0]

def get_public_ip(timeout=5) -> str:
    try:
        rc = subprocess.run(
            ["curl", "-sS", "-4", "--max-time", str(timeout), "ifconfig.me"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        ip = (rc.stdout or "").strip()
        socket.inet_aton(ip)  # validation IPv4
        return ip
    except Exception:
        return ""

def curl_http_code(args, timeout=8) -> (int, str):
    cmd = ["curl", "-sS", "-m", str(timeout), "-o", "/dev/null", "-w", "%{http_code}"] + args
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    code = (p.stdout or "").strip()
    return p.returncode, code if code else f"retcode_{p.returncode}"

# ========= TESTS PLEX =========
ALLOWED_OK = {"200", "301", "302", "401", "403"}

def test_local_plex_identity(plex_url: str, timeout=5):
    if not plex_url:
        return False, "no_plex_url"
    try:
        identity_url = plex_url.rstrip("/") + "/identity"
        rc, code = curl_http_code([identity_url], timeout=timeout)
        ok = (rc == 0 and code in ALLOWED_OK)
        return ok, code
    except Exception as e:
        return False, str(e)

def test_external_plex(domain_env: str, timeout=8):
    """
    Test externe : d'abord via DNS, sinon fallback via IP publique forcée.
    """
    if not domain_env:
        return ("error", "no_domain_configured")

    domain_url = _ensure_https(domain_env)
    host = _extract_host(domain_url)

    # Test via DNS
    try:
        rc, code = curl_http_code([f"https://{host}/identity"], timeout=timeout)
        if rc == 0 and code in ALLOWED_OK:
            return ("yes", code)  # DNS OK
        else:
            dns_fail = (rc, code)
    except Exception as e:
        dns_fail = ("error", str(e))

    # Fallback via IP publique
    pub_ip = get_public_ip()
    if not pub_ip:
        return ("no", f"dns_fail={dns_fail}, no_public_ip")
    try:
        rc, code = curl_http_code(["--resolve", f"{host}:443:{pub_ip}", f"https://{host}/identity"], timeout=timeout)
        if rc == 0 and code in ALLOWED_OK:
            return ("no", f"dns_fail={dns_fail}, via_ip_ok={code}")
        else:
            return ("no", f"dns_fail={dns_fail}, via_ip_fail={code}")
    except Exception as e:
        return ("error", f"dns_fail={dns_fail}, via_ip_error={e}")

# ========= OUTILS DOCKER/IP =========
def get_deluge_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "hostname", "-i"],
            capture_output=True, text=True
        )
        ip = result.stdout.strip().split()[0]
        return ip
    except Exception as e:
        raise RuntimeError(f"Could not detect IP inside deluge container: {e}")

def get_vpn_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    raise RuntimeError("Could not detect VPN IP on tun0 inside container")

def get_deluge_stats():
    stats = {"num_downloading": 0, "num_seeding": 0, "download_rate": 0.0, "upload_rate": 0.0, "num_peers": 0}
    try:
        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False,
        )
        try:
            client.connect()
        except Exception as conn_err:
            print(f"[ERROR - Deluge] RPC connection FAILED: {conn_err}")
            return None
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        for t in torrents.values():
            state = t[b"state"]
            if state == b"Downloading":
                stats["num_downloading"] += 1
            elif state == b"Seeding":
                stats["num_seeding"] += 1
        session_stats = client.call("core.get_session_status", ["download_rate", "upload_rate", "num_peers"])
        stats["download_rate"] = round(session_stats[b"download_rate"] / 1024, 2)
        stats["upload_rate"] = round(session_stats[b"upload_rate"] / 1024, 2)
        stats["num_peers"] = session_stats[b"num_peers"]
        return stats
    except Exception as e:
        print(f"[DEBUG - Deluge] RPC error: {e}")
        return None

# ========= COLLECTE =========
plex_msg_lines = []

# 1) Docker
critical_services = ["plex-server", "vpn", "deluge"]
for service in critical_services:
    status = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", service],
        capture_output=True, text=True
    )
    state = status.stdout.strip()
    plex_msg_lines.append(f"[SERVICE] {service} is {'running' if state == 'true' else 'NOT running'}")

# 2) VPN/Deluge IPs
try:
    vpn_ip_pub = subprocess.check_output(["docker", "exec", "vpn", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    deluge_ip_pub = subprocess.check_output(["docker", "exec", "deluge", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    vpn_ip_int = subprocess.check_output(["docker", "exec", "vpn", "hostname", "-i"]).decode().strip().split()[0]
    deluge_ip_int = subprocess.check_output(["docker", "exec", "deluge", "hostname", "-i"]).decode().strip().split()[0]
except Exception as e:
    plex_msg_lines.append(f"[NETWORK] Failed to retrieve VPN/Deluge IPs: {e}")

# 3) Internet access Deluge
try:
    internet_check = subprocess.run(["docker", "exec", "deluge", "ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
except Exception:
    internet_check = None

# 4) Speedtest
try:
    import speedtest
    st = speedtest.Speedtest()
    download_speed = st.download() / 1e6
    upload_speed = st.upload() / 1e6
except Exception:
    download_speed = upload_speed = 0.0

# 5) Plex tests
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
EXTERNAL_PLEX_URL = os.getenv("DOMAIN")

session_count = 0
users_connected = set()
transcode_count = 0
plex_connected = False

try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    plex_connected = True
    sessions = plex.sessions()
    session_count = len(sessions)
    for session in sessions:
        user = session.user.title
        users_connected.add(user)
        if hasattr(session, "transcodeSession") and session.transcodeSession is not None:
            transcode_count += 1
except Exception as e:
    print(f"[DEBUG - run_quick_check.py - PLEX - ERROR] Plex session fetch failed: {e}")

local_ok, local_code = test_local_plex_identity(PLEX_URL, timeout=5)
external_accessible, external_detail = test_external_plex(EXTERNAL_PLEX_URL, timeout=8)

# 6) Docker stats Plex
try:
    docker_stats_output = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemPerc}}", "plex-server"]
    ).decode().strip()
    cpu_str, mem_str = docker_stats_output.split()
    cpu = float(cpu_str.strip("%"))
    mem = float(mem_str.strip("%"))
except Exception:
    cpu = mem = 0.0

# 7) Transcode folder
TRANSCODE_PATH = "/app/Transcode"
try:
    if os.path.exists(TRANSCODE_PATH):
        usage = shutil.disk_usage(TRANSCODE_PATH)
        free_gb = usage.free / (1024**3)
    else:
        free_gb = None
except Exception:
    free_gb = None

# 8) Stats système
cpu_total = psutil.cpu_percent(interval=1)
ram_total = psutil.virtual_memory().percent
net_io = psutil.net_io_counters()
disk_io = psutil.disk_io_counters()
try:
    temps = psutil.sensors_temperatures()
    cpu_temp = temps["coretemp"][0].current if "coretemp" in temps and temps["coretemp"] else "N/A"
except Exception:
    cpu_temp = "N/A"

# 9) Storage
custom_mounts = ["/", "/mnt/media", "/mnt/media/extra"]
disk_status = {}
for mount in custom_mounts:
    try:
        usage = shutil.disk_usage(mount)
        disk_status[mount] = {
            "total_gb": round(usage.total / (1024**3)),
            "used_pct": round((usage.used / usage.total) * 100),
        }
    except Exception as e:
        pass

# 10) Deluge stats
deluge_stats = get_deluge_stats()

# 11) JSON final
data_entry = {
    "docker_services": {
        service: subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", service],
            capture_output=True, text=True
        ).stdout.strip() == "true"
        for service in ["plex-server", "vpn", "deluge"]
    },
    "network": {
        "vpn_ip": [ip for ip in [locals().get("vpn_ip_pub"), locals().get("vpn_ip_int")] if ip],
        "deluge_ip": [ip for ip in [locals().get("deluge_ip_pub"), locals().get("deluge_ip_int")] if ip],
        "internet_access": (internet_check.returncode == 0) if internet_check else False,
        "speedtest": {
            "download_mbps": round(download_speed, 2),
            "upload_mbps": round(upload_speed, 2),
        },
    },
    "plex": {
        "connected": plex_connected,
        "active_sessions": session_count,
        "unique_clients": len(users_connected),
        "transcoding_sessions": transcode_count,
        "cpu_usage": round(cpu, 2),
        "ram_usage": round(mem, 2),
        "transcode_folder_found": (free_gb is not None),
        "local_access": bool(local_ok),
        "local_detail": local_code,
        "external_access": external_accessible,
        "external_detail": external_detail,
    },
    "system": {
        "cpu_total": round(cpu_total, 2),
        "ram_total": round(ram_total, 2),
        "cpu_temp_c": round(cpu_temp, 2) if isinstance(cpu_temp, (int, float)) else 0.0,
        "internet_io": {
            "sent_mb": round(net_io.bytes_sent / (1024**2), 2),
            "received_mb": round(net_io.bytes_recv / (1024**2), 2),
        },
        "disk_io": {
            "read_mb": round(disk_io.read_bytes / (1024**2), 2),
            "write_mb": round(disk_io.write_bytes / (1024**2), 2),
        },
    },
    "deluge": {
        "num_downloading": deluge_stats["num_downloading"] if deluge_stats else 0,
        "num_seeding": deluge_stats["num_seeding"] if deluge_stats else 0,
        "download_rate_kbps": deluge_stats["download_rate"] if deluge_stats else 0.0,
        "upload_rate_kbps": deluge_stats["upload_rate"] if deluge_stats else 0.0,
        "num_peers": deluge_stats["num_peers"] if deluge_stats else 0,
    },
    "storage": disk_status,
    "performance": {"runtime_seconds": round(time.time() - start_time, 2)},
}

try:
    append_json_log(data_entry)
except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")
