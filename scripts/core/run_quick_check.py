#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File name : run_quick_check.py

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

# ========= CONFIG ENV (timeouts/retries & speedtest) =========
CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", "3"))
MAX_TIME = int(os.getenv("MAX_TIME", "10"))
RETRIES = int(os.getenv("RETRIES", "2"))

SPEEDTEST_ENABLED = os.getenv("SPEEDTEST_ENABLED", "1") == "1"
SPEEDTEST_COOLDOWN_SEC = int(os.getenv("SPEEDTEST_COOLDOWN_SEC", "7200"))  # 2h
SPEEDTEST_STATE_FILE = "/mnt/data/speedtest_state.json"

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
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")
    ),
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")
    ),
]
send_discord_message = None
for discord_path in discord_paths:
    if os.path.isfile(discord_path):
        print(f"[DEBUG] Using Discord notify at: {discord_path}")
        try:
            spec = importlib.util.spec_from_file_location(
                "discord_notify", discord_path
            )
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


# ---------- Helpers cURL (retries/timeouts unifiés) ----------
def curl_http_code(args) -> (int, str):
    cmd = [
        "curl",
        "-sS",
        "--retry",
        str(RETRIES),
        "--retry-all-errors",
        "--connect-timeout",
        str(CONNECT_TIMEOUT),
        "-m",
        str(MAX_TIME),
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
    ] + args
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    code = (p.stdout or "").strip()
    return p.returncode, code if code else f"retcode_{p.returncode}"


def curl_http_head(url: str) -> (int, str):
    cmd = [
        "curl",
        "-sS",
        "-I",
        "--retry",
        str(RETRIES),
        "--retry-all-errors",
        "--connect-timeout",
        str(CONNECT_TIMEOUT),
        "-m",
        str(MAX_TIME),
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        url,
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    code = (p.stdout or "").strip()
    return p.returncode, code if code else f"retcode_{p.returncode}"


# ---------- Test TCP bas niveau ----------
def tcp_port_open(host: str, port: int, timeout=2.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ---------- IP publique avec cache ----------
IP_CACHE_FILE = "/mnt/data/public_ip_cache.json"
IP_CACHE_TTL_SEC = int(os.getenv("PUBLIC_IP_CACHE_TTL_SEC", "600"))  # 10 min


def _write_ip_cache(ip: str):
    try:
        with open(IP_CACHE_FILE, "w") as f:
            json.dump({"ip": ip, "ts": int(time.time())}, f)
    except Exception:
        pass


def _read_ip_cache():
    try:
        with open(IP_CACHE_FILE, "r") as f:
            d = json.load(f)
        if int(time.time()) - int(d.get("ts", 0)) <= IP_CACHE_TTL_SEC and d.get("ip"):
            return d["ip"]
    except Exception:
        pass
    return ""


def get_public_ip(timeout=5) -> str:
    ip = _read_ip_cache()
    if ip:
        return ip
    for url in [
        "https://api.ipify.org",
        "https://ifconfig.me",
        "https://icanhazip.com",
    ]:
        try:
            rc = subprocess.run(
                ["curl", "-sS", "-4", "--max-time", str(timeout), url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            cand = (rc.stdout or "").strip()
            socket.inet_aton(cand)
            _write_ip_cache(cand)
            return cand
        except Exception:
            continue
    return ""


# ========= TESTS PLEX =========
ALLOWED_OK = {"200", "301", "302", "401", "403"}


def _url_host_port_from_plex_url(plex_url: str):
    if not plex_url:
        return None, 32400
    rest = re.sub(r"^https?://", "", plex_url)
    hostport = rest.split("/", 1)[0]
    if ":" in hostport:
        host, port = hostport.split(":", 1)
        try:
            return host, int(port)
        except Exception:
            return host, 32400
    return hostport, 32400


def test_local_plex_identity(plex_url: str):
    """
    Local : TCP (host:port) -> HEAD /identity -> (fallback) GET /identity
    """
    if not plex_url:
        return False, "no_plex_url"
    host, port = _url_host_port_from_plex_url(plex_url)
    if not host:
        return False, "no_host_in_url"

    if not tcp_port_open(host, port, timeout=min(2.5, CONNECT_TIMEOUT)):
        return False, f"tcp_closed_{host}:{port}"

    identity_url = plex_url.rstrip("/") + "/identity"
    rc_h, code_h = curl_http_head(identity_url)
    if rc_h == 0 and code_h in ALLOWED_OK:
        return True, f"HEAD_{code_h}"

    rc, code = curl_http_code([identity_url])
    ok = rc == 0 and code in ALLOWED_OK
    return ok, code


def resolve_a_records(host: str):
    try:
        return list(
            {ai[4][0] for ai in socket.getaddrinfo(host, None, family=socket.AF_INET)}
        )
    except Exception:
        return []


def test_external_plex(domain_env: str):
    """
    Définition "accessible en ligne":
    - Le DNS du domaine DOIT contenir l'IP publique courante
    - ET un HEAD via DNS sur https://<domaine>/identity doit retourner un code OK (200/301/302/401/403)
    Sinon -> "no" avec un détail expliquant la cause.
    """
    if not domain_env:
        return ("error", "no_domain_configured")

    domain_url = _ensure_https(domain_env)
    host = _extract_host(domain_url)
    identity_url = f"https://{host}/identity"

    pub_ip = get_public_ip(timeout=min(5, MAX_TIME))
    if not pub_ip:
        return ("no", "no_public_ip")

    a_records = resolve_a_records(host)
    if not a_records:
        return ("no", f"dns_no_a_records (resolved=[]; public_ip={pub_ip})")

    if pub_ip not in a_records:
        return ("no", f"dns_mismatch (resolved={a_records}; public_ip={pub_ip})")

    try:
        rc, code = curl_http_head(identity_url)
        if rc == 0 and code in ALLOWED_OK:
            return ("yes", f"HEAD_{code}")
        else:
            return ("no", f"dns_ok_but_http_fail ({code})")
    except Exception as e:
        return ("no", f"dns_ok_but_http_error ({e})")


# ========= OUTILS DOCKER/IP =========
def get_deluge_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "ip", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "hostname", "-i"],
            capture_output=True,
            text=True,
        )
        ip = result.stdout.strip().split()[0]
        return ip
    except Exception as e:
        raise RuntimeError(f"Could not detect IP inside deluge container: {e}")


def get_vpn_ip():
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    raise RuntimeError("Could not detect VPN IP on tun0 inside container")


def get_deluge_stats():
    stats = {
        "num_downloading": 0,
        "num_seeding": 0,
        "download_rate": 0.0,
        "upload_rate": 0.0,
        "num_peers": 0,
    }
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
        session_stats = client.call(
            "core.get_session_status", ["download_rate", "upload_rate", "num_peers"]
        )
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
        capture_output=True,
        text=True,
    )
    state = status.stdout.strip()
    plex_msg_lines.append(
        f"[SERVICE] {service} is {'running' if state == 'true' else 'NOT running'}"
    )

# 2) VPN/Deluge IPs
try:
    vpn_ip_pub = (
        subprocess.check_output(
            ["docker", "exec", "vpn", "curl", "-s", "https://api.ipify.org"]
        )
        .decode()
        .strip()
    )
    deluge_ip_pub = (
        subprocess.check_output(
            ["docker", "exec", "deluge", "curl", "-s", "https://api.ipify.org"]
        )
        .decode()
        .strip()
    )
    vpn_ip_int = (
        subprocess.check_output(["docker", "exec", "vpn", "hostname", "-i"])
        .decode()
        .strip()
        .split()[0]
    )
    deluge_ip_int = (
        subprocess.check_output(["docker", "exec", "deluge", "hostname", "-i"])
        .decode()
        .strip()
        .split()[0]
    )
except Exception as e:
    plex_msg_lines.append(f"[NETWORK] Failed to retrieve VPN/Deluge IPs: {e}")

# 3) Internet access Deluge
try:
    internet_check = subprocess.run(
        ["docker", "exec", "deluge", "ping", "-c", "1", "8.8.8.8"],
        stdout=subprocess.DEVNULL,
    )
except Exception:
    internet_check = None

# 4) Speedtest (rempli en fin si conditions OK)
download_speed = 0.0
upload_speed = 0.0


def _can_run_speedtest_now() -> bool:
    try:
        with open(SPEEDTEST_STATE_FILE, "r") as f:
            st = json.load(f)
        last = int(st.get("last", 0))
        if time.time() - last < SPEEDTEST_COOLDOWN_SEC:
            return False
    except Exception:
        pass
    return True


def _mark_speedtest_ran():
    try:
        with open(SPEEDTEST_STATE_FILE, "w") as f:
            json.dump({"last": int(time.time())}, f)
    except Exception:
        pass


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
        if (
            hasattr(session, "transcodeSession")
            and session.transcodeSession is not None
        ):
            transcode_count += 1
except Exception as e:
    print(f"[DEBUG - run_quick_check.py - PLEX - ERROR] Plex session fetch failed: {e}")

local_ok, local_code = test_local_plex_identity(PLEX_URL)
external_accessible, external_detail = test_external_plex(EXTERNAL_PLEX_URL)

# 6) Docker stats Plex
try:
    docker_stats_output = (
        subprocess.check_output(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.CPUPerc}} {{.MemPerc}}",
                "plex-server",
            ]
        )
        .decode()
        .strip()
    )
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
    cpu_temp = (
        temps["coretemp"][0].current
        if "coretemp" in temps and temps["coretemp"]
        else "N/A"
    )
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
    except Exception:
        pass

# 10) Deluge stats
deluge_stats = get_deluge_stats()

# 11) Speedtest en FIN de script (limité et avec cooldown)
should_try_speedtest = (
    SPEEDTEST_ENABLED
    and _can_run_speedtest_now()
    and (local_ok or plex_connected)  # éviter de stresser si Plex KO localement
)
if should_try_speedtest:
    try:
        import speedtest

        st = speedtest.Speedtest()
        download_speed = st.download() / 1e6
        # Upload moins fréquent pour réduire l'impact
        if int(time.time()) % 3 == 0:
            upload_speed = st.upload() / 1e6
        else:
            upload_speed = 0.0
        _mark_speedtest_ran()
    except Exception:
        download_speed = upload_speed = 0.0

# 12) JSON final
data_entry = {
    "docker_services": {
        service: subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", service],
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "true"
        for service in ["plex-server", "vpn", "deluge"]
    },
    "network": {
        "vpn_ip": [
            ip for ip in [locals().get("vpn_ip_pub"), locals().get("vpn_ip_int")] if ip
        ],
        "deluge_ip": [
            ip
            for ip in [locals().get("deluge_ip_pub"), locals().get("deluge_ip_int")]
            if ip
        ],
        "internet_access": (
            (internet_check.returncode == 0) if internet_check else False
        ),
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
        "local_detail": str(local_code),
        "external_access": str(external_accessible),  # "yes" / "no" / "error"
        "external_detail": str(external_detail),
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
    "meta": {
        "retries": RETRIES,
        "connect_timeout": CONNECT_TIMEOUT,
        "max_time": MAX_TIME,
        "speedtest_enabled": SPEEDTEST_ENABLED,
        "speedtest_cooldown_sec": SPEEDTEST_COOLDOWN_SEC,
        "public_ip_cache_ttl_sec": IP_CACHE_TTL_SEC,
    },
}

try:
    append_json_log(data_entry)
except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")
