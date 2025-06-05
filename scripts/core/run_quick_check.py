import os
import subprocess
import logging
import time
import psutil
import shutil
from dotenv import load_dotenv
from plexapi.server import PlexServer
import importlib.util
import logging
import json
from datetime import datetime
from deluge_client import DelugeRPCClient
import re

start_time = time.time()
mode = "debug"
discord_connected = False
print("[DEBUG - run_quick_check.py - INIT - 1] Script initiated")

print("[DEBUG - run_quick_check.py - ENV - 1] Attempting to load /app/.env")
if load_dotenv("/app/.env"):
    print("[DEBUG - run_quick_check.py - ENV - 2] Loaded /app/.env")
    env_loaded = True
else:
    print("[DEBUG - run_quick_check.py - ENV - 3] No .env file found.")
    env_loaded = False


deluge_config = {
    "host": "localhost",
    "port": 58846,
    "username": "localclient",
    "password": "e0db9d7d51b2c62b7987031174607aa822f94bc9",
#    "password": os.getenv("DELUGE_PASSWORD"),
}

# Setup Discord
print("[DEBUG - run_quick_check.py - INIT - 2] Initializing Discord connection")

discord_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),          # dans Docker
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),    # hors Docker
]

discord_connected = False
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

if not send_discord_message:
    print("[DEBUG - run_quick_check.py - DISCORD - FAIL] Could not load Discord notifier module.")

def get_deluge_ip():
    """
    Récupère l'adresse IP de l'interface principale dans le conteneur Docker Deluge.
    Tente d'extraire l'adresse associée à `tun0` si elle existe, sinon celle de l'hôte.
    """
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
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
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[DEBUG - get_vpn_ip] {e}")
    raise RuntimeError("Could not detect VPN IP on tun0 inside container")

# Setup logging
logging.basicConfig(
    filename="/mnt/data/entry_log_quick_check.log",
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
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


plex_msg_lines = []

# Check Docker service status
print("[DEBUG - run_quick_check.py - DOCKER - 1] Checking critical Docker services")
critical_services = ["plex-server", "vpn", "deluge"]
for service in critical_services:
    status = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", service], capture_output=True, text=True)
    state = status.stdout.strip()
    if state == "true":
        plex_msg_lines.append(f"[SERVICE] {service} is running")
    else:
        plex_msg_lines.append(f"[SERVICE] {service} is NOT running")

# Check VPN and Deluge IPs (public and internal)
print("[DEBUG - run_quick_check.py - NETWORK - 1] Fetching VPN and Deluge IPs")
try:
    vpn_ip_pub = subprocess.check_output(["docker", "exec", "vpn", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    deluge_ip_pub = subprocess.check_output(["docker", "exec", "deluge", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    vpn_ip_int = subprocess.check_output(["docker", "exec", "vpn", "hostname", "-i"]).decode().strip().split()[0]
    deluge_ip_int = subprocess.check_output(["docker", "exec", "deluge", "hostname", "-i"]).decode().strip().split()[0]

    plex_msg_lines.append(f"[VPN IP] {vpn_ip_pub}")
    plex_msg_lines.append(f"[DELUGE IP] {deluge_ip_pub}")
    plex_msg_lines.append(f"[VPN IP] {vpn_ip_int}")
    plex_msg_lines.append(f"[DELUGE IP] {deluge_ip_int}")
except Exception as e:
    plex_msg_lines.append(f"[NETWORK] Failed to retrieve VPN/Deluge IPs: {e}")

# Internet access and speed test from Deluge container
print("[DEBUG - run_quick_check.py - NETWORK - 2] Internet access and speed test from Deluge")
try:
    internet_check = subprocess.run(["docker", "exec", "deluge", "ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
    if internet_check.returncode == 0:
        plex_msg_lines.append("[INTERNET ACCESS] Deluge has internet access")
    else:
        plex_msg_lines.append("[INTERNET ACCESS] Deluge does NOT have internet access")
except:
    plex_msg_lines.append("[INTERNET ACCESS] Failed to perform connectivity check")

# Internet speed test
print("[DEBUG - run_quick_check.py - NETWORK - 3] Performing speed test")
try:
    import speedtest
    st = speedtest.Speedtest()
    download_speed = st.download() / 1e6
    upload_speed = st.upload() / 1e6
    plex_msg_lines.append(f"[SPEEDTEST] Download: {download_speed:.2f} Mbps | Upload: {upload_speed:.2f} Mbps")
except:
    plex_msg_lines.append("[SPEEDTEST] Failed to perform speed test")

# Plex test
print("[DEBUG - run_quick_check.py - PLEX - 1] Starting PLEX test suite")
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    print("[DEBUG - run_quick_check.py - PLEX - 2] Connected to Plex")

    sessions = plex.sessions()
    session_count = len(sessions)
    print(f"[DEBUG - run_quick_check.py - PLEX - 3] Active Plex sessions: {session_count}")
    plex_msg_lines.append(f"[PLEX STATUS] Active sessions: {session_count}")

    users_connected = set()
    transcode_count = 0
    for session in sessions:
        try:
            media_title = session.title
            user = session.user.title
            users_connected.add(user)
            player = session.players[0].product if session.players else "Unknown"
            video_decision = session.videoDecision if hasattr(session, 'videoDecision') else "N/A"
            audio_codec = session.media[0].audioCodec if session.media else "N/A"
            video_codec = session.media[0].videoCodec if session.media else "N/A"
            resolution = f"{session.media[0].videoResolution}p" if session.media else "N/A"
            duration = int(session.viewOffset / 1000) if hasattr(session, 'viewOffset') else 0
            transcode_active = hasattr(session, 'transcodeSession') and session.transcodeSession is not None

            print(f"[DEBUG - run_quick_check.py - PLEX - 4] {user} watching {media_title} on {player} - {video_decision}, {video_codec}/{audio_codec}, {resolution}, {duration}s")

            plex_msg_lines.append(f"[SESSION] {user} watching {media_title} on {player}")
            plex_msg_lines.append(f"  - Type: {video_decision} | Codec: {video_codec}/{audio_codec} | Resolution: {resolution} | Duration: {duration}s")

            if transcode_active:
                transcode_count += 1
        except Exception as e:
            print(f"[DEBUG - run_quick_check.py - PLEX - Error] Transcode check error: {e}")

    plex_msg_lines.append(f"[INFO] Transcoding sessions: {transcode_count}")
    plex_msg_lines.append(f"[INFO] Unique clients connected: {len(users_connected)}")

    response = subprocess.run(["curl", "-s", "--max-time", "5", f"{PLEX_URL}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if response.returncode == 0:
        plex_msg_lines.append("[LOCAL ACCESS] Plex accessible locally")
    else:
        plex_msg_lines.append("[LOCAL ACCESS] Plex NOT accessible locally")

    EXTERNAL_PLEX_URL = os.getenv("DOMAIN")
    external_accessible = "unknown"

    if EXTERNAL_PLEX_URL:
        try:
            response_ext = subprocess.run(
                ["curl", "-s", "--max-time", "5", EXTERNAL_PLEX_URL],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            external_accessible = "yes" if response_ext.returncode == 0 else "no"
        except Exception as e:
            external_accessible = "error"
        plex_msg_lines.append(f"[EXTERNAL ACCESS] Plex accessible externally: {external_accessible}")
    else:
        plex_msg_lines.append("[EXTERNAL ACCESS] No external URL configured")

    for proc in psutil.process_iter(['name', 'cmdline']):
        if 'plex' in ' '.join(proc.info.get('cmdline', [])).lower():
            try:
                cpu = proc.cpu_percent(interval=1)
                mem = proc.memory_percent()
                plex_msg_lines.append(f"[PROCESS] Plex CPU usage: {cpu:.2f}% | RAM usage: {mem:.2f}%")
            except:
                pass
            break

    TRANSCODE_PATH = "/home/paul/homelab/media_serveur/Rober-2.0/config/plex/transcode/Transcode"

    try:
        if os.path.exists(TRANSCODE_PATH):
            usage = shutil.disk_usage(TRANSCODE_PATH)
            free_gb = usage.free / (1024**3)
            plex_msg_lines.append(f"[DISK] Transcode free space: {free_gb:.2f} GB")
        else:
            plex_msg_lines.append(f"[DISK] Transcode folder not found at {TRANSCODE_PATH}")
    except Exception as e:
       plex_msg_lines.append(f"[DISK] Failed to access {TRANSCODE_PATH}: {e}")


    print("[DEBUG - run_quick_check.py - SYSTEM - 1] Gathering system stats")
    cpu_total = psutil.cpu_percent(interval=1)
    ram_total = psutil.virtual_memory().percent
    net_io = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()
    try:
        temps = psutil.sensors_temperatures()
        cpu_temp = temps['coretemp'][0].current if 'coretemp' in temps else 'N/A'
    except:
        cpu_temp = 'N/A'

    plex_msg_lines.append(f"[SYSTEM] Total CPU usage: {cpu_total:.2f}%")
    plex_msg_lines.append(f"[SYSTEM] Total RAM usage: {ram_total:.2f}%")
    plex_msg_lines.append(f"[SYSTEM] Internet I/O - Sent: {net_io.bytes_sent / (1024**2):.2f} MB | Received: {net_io.bytes_recv / (1024**2):.2f} MB")
    plex_msg_lines.append(f"[SYSTEM] Disk I/O - Read: {disk_io.read_bytes / (1024**2):.2f} MB | Write: {disk_io.write_bytes / (1024**2):.2f} MB")
    plex_msg_lines.append(f"[SYSTEM] CPU Temperature: {cpu_temp}")

    end_time = time.time()
    duration = end_time - start_time
    plex_msg_lines.append(f"[RUNTIME] Script execution time: {duration:.2f} seconds")

    for line in plex_msg_lines:
        print(f"[DEBUG - run_quick_check.py - PLEX - INFO] {line}")
    send_discord_message("Quick data acquisition : done")
    discord_connected = True

except Exception as e:
    print(f"[DEBUG - run_quick_check.py - PLEX - ERROR] Plex session fetch failed: {e}")
    send_discord_message("Quick data acquisition : done with error")
    discord_connected = True

if discord_connected:
    print("[DEBUG - run_quick_check.py - DISCORD - SUCCESS] Discord message sent successfully")
else:
    print("[DEBUG - run_quick_check.py - DISCORD - FAIL] No Discord message sent")


def get_deluge_stats():
    stats = {
        "num_downloading": 0,
        "num_seeding": 0,
        "download_rate": 0.0,
        "upload_rate": 0.0,
        "num_peers": 0
    }

    try:
        if mode == "debug":
            print("[DEBUG - Deluge] Connecting to RPC...")

        client = DelugeRPCClient(
            deluge_config["host"],
            deluge_config["port"],
            deluge_config["username"],
            deluge_config["password"],
            False
        )

        try: 
            client.connect()
            print("[DEBUG - Deluge] RPC connection successful")
        except Exception as conn_err:
            print(f"[ERROR - Deluge] RPC connection FAILED: {conn_err}")
            return None  # Stop here if connection fails

        # Get per-torrent states
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        for t in torrents.values():
            state = t[b"state"]
            if state == b"Downloading":
                stats["num_downloading"] += 1
            elif state == b"Seeding":
                stats["num_seeding"] += 1

        # Get session-wide stats
        session_stats = client.call("core.get_session_status", [
            "download_rate", "upload_rate", "num_peers"
        ])
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

# Récupération des IPs avec fallback et ajout aux logs
try:
    vpn_ip_int = get_vpn_ip()
    deluge_ip_int = get_deluge_ip()
    deluge_ip_pub = subprocess.check_output(["docker", "exec", "deluge", "curl", "-s", "https://api.ipify.org"]).decode().strip()
    
    plex_msg_lines.append(f"[VPN IP] {vpn_ip_pub}")
    plex_msg_lines.append(f"[DELUGE IP] {deluge_ip_pub}")
    plex_msg_lines.append(f"[VPN IP] {vpn_ip_int}")
    plex_msg_lines.append(f"[DELUGE IP] {deluge_ip_int}")
except Exception as e:
    plex_msg_lines.append(f"[NETWORK] Failed to retrieve VPN/Deluge IPs: {e}")

except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")

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
    # Récupération des statistiques Deluge
    deluge_stats = get_deluge_stats() if 'get_deluge_stats' in globals() else None

    data_entry = {
        "docker_services": {
            service: subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", service],
                capture_output=True, text=True
            ).stdout.strip() == "true"
            for service in ["plex-server", "vpn", "deluge"]
        },
        "network": {
            "vpn_ip": [vpn_ip_pub, vpn_ip_int] if 'vpn_ip_pub' in locals() and 'vpn_ip_int' in locals() else [],
            "deluge_ip": [deluge_ip_pub, deluge_ip_int] if 'deluge_ip_pub' in locals() and 'deluge_ip_int' in locals() else [],
            "internet_access": internet_check.returncode == 0 if 'internet_check' in locals() else False,
            "speedtest": {
                "download_mbps": round(download_speed, 2) if 'download_speed' in locals() else 0.0,
                "upload_mbps": round(upload_speed, 2) if 'upload_speed' in locals() else 0.0
            }
        },
        "plex": {
            "connected": 'plex' in locals(),
            "active_sessions": session_count if 'session_count' in locals() else 0,
            "unique_clients": len(users_connected) if 'users_connected' in locals() else 0,
            "transcoding_sessions": transcode_count if 'transcode_count' in locals() else 0,
            "cpu_usage": round(cpu, 2) if 'cpu' in locals() else 0.0,
            "ram_usage": round(mem, 2) if 'mem' in locals() else 0.0,
            "transcode_folder_found": 'free_gb' in locals(),
            "local_access": True,
            "external_access": external_accessible
        },
        "system": {
            "cpu_total": round(cpu_total, 2) if 'cpu_total' in locals() else 0.0,
            "ram_total": round(ram_total, 2) if 'ram_total' in locals() else 0.0,
            "cpu_temp_c": round(cpu_temp, 2) if isinstance(cpu_temp, float) else 0.0,
            "internet_io": {
                "sent_mb": round(net_io.bytes_sent / (1024**2), 2) if 'net_io' in locals() else 0.0,
                "received_mb": round(net_io.bytes_recv / (1024**2), 2) if 'net_io' in locals() else 0.0
            },
            "disk_io": {
                "read_mb": round(disk_io.read_bytes / (1024**2), 2) if 'disk_io' in locals() else 0.0,
                "write_mb": round(disk_io.write_bytes / (1024**2), 2) if 'disk_io' in locals() else 0.0
            }
        },
        "deluge": {
            "num_downloading": deluge_stats["num_downloading"] if deluge_stats else 0,
            "num_seeding": deluge_stats["num_seeding"] if deluge_stats else 0,
            "download_rate_kbps": deluge_stats["download_rate"] if deluge_stats else 0.0,
            "upload_rate_kbps": deluge_stats["upload_rate"] if deluge_stats else 0.0,
            "num_peers": deluge_stats["num_peers"] if deluge_stats else 0
        },
        "storage": disk_status,
        "performance": {
            "runtime_seconds": round(duration, 2) if 'duration' in locals() else 0.0
        }
    }

    append_json_log(data_entry)


except Exception as e:
    logging.error(f"[JSON LOGGING] Failed to append JSON log: {e}")

