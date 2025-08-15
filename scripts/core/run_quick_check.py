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
    "password": "e0db9d7d51b2c62b7987031174607aa822f94bc9",  # à remplacer par env si souhaité
    # "password": os.getenv("DELUGE_PASSWORD"),
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
    os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),   # dans Docker
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),  # hors Docker
]

send_discord_message = None
for discord_path in discord_paths:
    if os.path.isfile(discord_path):
        print(f"[DEBUG - run_quick_check.py - DISCORD - Found] Using: {discord_path}")
        try:
            spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
            discord_notify = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord_notify)
            send_discord_message = discord_notify.send_discord_message
            break
        except Exception as e:
            print(f"[DEBUG - run_quick_check.py - DISCORD - Error] Failed to import module: {e}")
    else:
        print(f"[DEBUG - run_quick_check.py - DISCORD - Missing] File not found: {discord_path}")

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
    """
    Exécute curl et renvoie (returncode, http_code_ou_msg)
    args : liste déjà prête (sans -m/-w/-o)
    """
    cmd = ["curl", "-sS", "-m", str(timeout), "-o", "/dev/null", "-w", "%{http_code}"] + args
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    code = (p.stdout or "").strip()
    return p.returncode, code if code else f"retcode_{p.returncode}"

# ========= TESTS PLEX =========
ALLOWED_OK = {"200", "301", "302", "401", "403"}

def test_local_plex_identity(plex_url: str, timeout=5):
    """
    Test local minimal de 'liveness' Plex via /identity (HTTP sans token).
    Retourne: (True/False, http_code_ou_msg)
    """
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
    Test externe robuste Plex:
      - /identity (léger)
      - HTTPS
      - --resolve DOMAIN:443:PUB_IP (bypass DNS si possible)
    Retourne: ("yes"|"no"|"error", http_code_ou_msg)
    """
    if not domain_env:
        return ("error", "no_domain_configured")

    domain_url = _ensure_https(domain_env)
    host = _extract_host(domain_url)
    pub_ip = get_public_ip()

    args = []
    if pub_ip:
        args += ["--resolve", f"{host}:443:{pub_ip}"]
    args.append(f"https://{host}/identity")

    try:
        rc, code = curl_http_code(args, timeout=timeout)
        if rc == 0 and code in ALLOWED_OK:
            return ("yes", code)
        else:
            return ("no", code)
    except Exception as e:
        return ("error", str(e))

# ========= OUTILS DOCKER/IP =========
def get_deluge_ip():
    """
    IP interne prioritaire sur tun0 si présent, sinon IP du conteneur.
    """
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[DEBUG - get_deluge_ip - tun0] {e}")

    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "hostname", "-i"],
            capture_output=True, text=True
        )
        ip = result.stdout.strip().split()[0]
        return ip
    except Exception as e:
        raise RuntimeError(f"[DEBUG - get_deluge_ip - fallback] Could not detect IP inside deluge container: {e}")

def get_vpn_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[DEBUG - get_vpn_ip] {e}")
    raise RuntimeError("Could not detect VPN IP on tun0 inside container")

def get_deluge_stats():
    stats = {"num_downloading": 0, "num_seeding": 0, "download_rate": 0.0, "upload_rate": 0.0, "num_peers": 0}
    try:
        if mode == "debug":
            print("[DEBUG - Deluge] Connecting to RPC...")

        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False,
        )

        try:
            client.connect()
            print("[DEBUG - Deluge] RPC connection successful")
        except Exception as conn_err:
            print(f"[ERROR - Deluge] RPC connection FAILED: {conn_err}")
            return None

        # États par torrent
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        for t in torrents.values():
            state = t[b"state"]
            if state == b"Downloading":
                stats["num_downloading"] += 1
            elif state == b"Seeding":
                stats["num_seeding"] += 1

        # Stats session
        session_stats = client.call("core.get_session_status", ["download_rate", "upload_rate", "num_peers"])
        stats["download_rate"] = round(session_stats[b"download_rate"] / 1024, 2)  # KB/s
        stats["upload_rate"] = round(session_stats[b"upload_rate"] / 1024, 2)      # KB/s
        stats["num_peers"] = session_stats[b"num_peers"]

        if mode == "debug":
            print(f"[DEBUG - Deluge] Stats: {stats}")
        return stats

    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - Deluge] RPC error: {e}")
        return None

# ========= COLLECTE =========
plex_msg_lines = []

# 1) Services Docker critiques
print("[DEBUG - run_quick_check.py - DOCKER - 1] Checking critical Docker services")
critical_services = ["plex-server", "vpn", "deluge"]
for service in critical_services:
    status = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", service],
        capture_output=True, text=True
    )
    state = status.stdout.strip()
    if state == "true":
        plex_msg_lines.append(f"[SERVICE] {service} is running")
    else:
        plex_msg_lines.append(f"[SERVICE] {service} is NOT running")

# 2) IPs VPN/Deluge (publiques & internes)
print("[DEBUG - run_quick_check.py - NETWORK - 1] Fetching VPN and Deluge IPs")
try:
    vpn_ip_pub = subprocess.check_output(["docker", "exec", "vpn", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    deluge_ip_pub = subprocess.check_output(["docker", "exec", "deluge", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    vpn_ip_int = subprocess.check_output(["docker", "exec", "vpn", "hostname", "-i"]).decode().strip().split()[0]
    deluge_ip_int = subprocess.check_output(["docker", "exec", "deluge", "hostname", "-i"]).decode().strip().split()[0]

    plex_msg_lines.append(f"[VPN IP - public] {vpn_ip_pub}")
    plex_msg_lines.append(f"[DELUGE IP - public] {deluge_ip_pub}")
    plex_msg_lines.append(f"[VPN IP - internal] {vpn_ip_int}")
    plex_msg_lines.append(f"[DELUGE IP - internal] {deluge_ip_int}")
except Exception as e:
    plex_msg_lines.append(f"[NETWORK] Failed to retrieve VPN/Deluge IPs: {e}")

# 3) Accès internet Deluge
print("[DEBUG - run_quick_check.py - NETWORK - 2] Internet access and speed test from Deluge")
try:
    internet_check = subprocess.run(["docker", "exec", "deluge", "ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
    if internet_check.returncode == 0:
        plex_msg_lines.append("[INTERNET ACCESS] Deluge has internet access")
    else:
        plex_msg_lines.append("[INTERNET ACCESS] Deluge does NOT have internet access")
except Exception:
    internet_check = None
    plex_msg_lines.append("[INTERNET ACCESS] Failed to perform connectivity check")

# 4) Speedtest (best effort)
print("[DEBUG - run_quick_check.py - NETWORK - 3] Performing speed test")
try:
    import speedtest
    st = speedtest.Speedtest()
    download_speed = st.download() / 1e6
    upload_speed = st.upload() / 1e6
    plex_msg_lines.append(f"[SPEEDTEST] Download: {download_speed:.2f} Mbps | Upload: {upload_speed:.2f} Mbps")
except Exception:
    download_speed = upload_speed = 0.0
    plex_msg_lines.append("[SPEEDTEST] Failed to perform speed test")

# 5) PLEX : API + sessions + tests /identity (local & externe)
print("[DEBUG - run_quick_check.py - PLEX - 1] Starting PLEX test suite")
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
EXTERNAL_PLEX_URL = os.getenv("DOMAIN")  # peut être un host; on forcerá https si absent

session_count = 0
users_connected = set()
transcode_count = 0
plex_connected = False

try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    plex_connected = True
    print("[DEBUG - run_quick_check.py - PLEX - 2] Connected to Plex")

    sessions = plex.sessions()
    session_count = len(sessions)
    plex_msg_lines.append(f"[PLEX STATUS] Active sessions: {session_count}")

    for session in sessions:
        try:
            media_title = session.title
            user = session.user.title
            users_connected.add(user)
            player = session.players[0].product if session.players else "Unknown"
            video_decision = getattr(session, "videoDecision", "N/A")
            audio_codec = session.media[0].audioCodec if session.media else "N/A"
            video_codec = session.media[0].videoCodec if session.media else "N/A"
            resolution = f"{session.media[0].videoResolution}p" if session.media else "N/A"
            duration = int(session.viewOffset / 1000) if hasattr(session, "viewOffset") else 0
            transcode_active = hasattr(session, "transcodeSession") and session.transcodeSession is not None

            plex_msg_lines.append(f"[SESSION] {user} watching {media_title} on {player}")
            plex_msg_lines.append(
                f"  - Type: {video_decision} | Codec: {video_codec}/{audio_codec} | Resolution: {resolution} | Duration: {duration}s"
            )
            if transcode_active:
                transcode_count += 1
        except Exception as e:
            print(f"[DEBUG - run_quick_check.py - PLEX - Error] Transcode check error: {e}")

except Exception as e:
    print(f"[DEBUG - run_quick_check.py - PLEX - ERROR] Plex session fetch failed: {e}")

# Test /identity LOCAL
local_ok, local_code = test_local_plex_identity(PLEX_URL, timeout=5)
plex_msg_lines.append(f"[LOCAL ACCESS] /identity: { 'OK' if local_ok else 'FAIL' } (code: {local_code})")

# Test /identity EXTERNE
external_accessible, external_detail = test_external_plex(EXTERNAL_PLEX_URL, timeout=8)
plex_msg_lines.append(f"[EXTERNAL ACCESS] /identity: {external_accessible} (detail: {external_detail})")

# 6) Ressources container Plex
try:
    docker_stats_output = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemPerc}}", "plex-server"]
    ).decode().strip()
    cpu_str, mem_str = docker_stats_output.split()
    cpu = float(cpu_str.strip("%"))
    mem = float(mem_str.strip("%"))
    plex_msg_lines.append(f"[PROCESS] Plex CPU usage (Docker): {cpu:.2f}% | RAM usage: {mem:.2f}%")
except Exception as e:
    cpu = 0.0
    mem = 0.0
    plex_msg_lines.append(f"[PROCESS] Failed to get Plex usage via docker stats: {e}")

# 7) Espace Transcode
TRANSCODE_PATH = "/app/Transcode"
try:
    if os.path.exists(TRANSCODE_PATH):
        usage = shutil.disk_usage(TRANSCODE_PATH)
        free_gb = usage.free / (1024**3)
        plex_msg_lines.append(f"[DISK] Transcode free space: {free_gb:.2f} GB")
    else:
        free_gb = None
        plex_msg_lines.append(f"[DISK] Transcode folder not found at {TRANSCODE_PATH}")
except Exception as e:
    free_gb = None
    plex_msg_lines.append(f"[DISK] Failed to access {TRANSCODE_PATH}: {e}")

# 8) Stats système
print("[DEBUG - run_quick_check.py - SYSTEM - 1] Gathering system stats")
cpu_total = psutil.cpu_percent(interval=1)
ram_total = psutil.virtual_memory().percent
net_io = psutil.net_io_counters()
disk_io = psutil.disk_io_counters()
try:
    temps = psutil.sensors_temperatures()
    cpu_temp = temps["coretemp"][0].current if "coretemp" in temps and temps["coretemp"] else "N/A"
except Exception:
    cpu_temp = "N/A"

plex_msg_lines.append(f"[SYSTEM] Total CPU usage: {cpu_total:.2f}%")
plex_msg_lines.append(f"[SYSTEM] Total RAM usage: {ram_total:.2f}%")
plex_msg_lines.append(f"[SYSTEM] Internet I/O - Sent: {net_io.bytes_sent / (1024**2):.2f} MB | Received: {net_io.bytes_recv / (1024**2):.2f} MB")
plex_msg_lines.append(f"[SYSTEM] Disk I/O - Read: {disk_io.read_bytes / (1024**2):.2f} MB | Write: {disk_io.write_bytes / (1024**2):.2f} MB")
plex_msg_lines.append(f"[SYSTEM] CPU Temperature: {cpu_temp}")

end_time = time.time()
duration = end_time - start_time
plex_msg_lines.append(f"[RUNTIME] Script execution time: {duration:.2f} seconds")

# Affichage console
for line in plex_msg_lines:
    print(f"[DEBUG - run_quick_check.py - PLEX - INFO] {line}")

# Envoi Discord (si souhaité)
if send_discord_message:
    try:
        send_discord_message("Quick data acquisition: done")
        print("[DEBUG - run_quick_check.py - DISCORD - SUCCESS] Discord message sent successfully")
    except Exception as e:
        print(f"[DEBUG - run_quick_check.py - DISCORD - FAIL] {e}")
else:
    print("[DEBUG - run_quick_check.py - DISCORD - SKIP] Notifier not available")

# 9) Disques (sélection)
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
        print(f"[DEBUG - STORAGE - Error] {mount}: {e}")

# 10) Stats Deluge pour JSON
deluge_stats = get_deluge_stats()

# 11) Construction JSON fiable
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
        "cpu_usage": round(cpu, 2),     # ne PAS diviser par core_count
        "ram_usage": round(mem, 2),
        "transcode_folder_found": (free_gb is not None),
        "local_access": bool(local_ok),
        "local_detail": local_code,
        "external_access": external_accessible,   # "yes" | "no" | "error"
        "external_detail": external_detail,       # http_code ou message
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
    "performance": {"runtime_seconds": round(duration, 2)},
}

try:
    append_json_log(data_entry)
except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")
