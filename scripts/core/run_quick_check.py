import os
import sys
import subprocess
import logging
import json
import time
import re
import psutil
from dotenv import load_dotenv
from deluge_client import DelugeRPCClient
from plexapi.server import PlexServer
import importlib.util

mode = "debug"
start_time = time.time()

# Discord setup
discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

# Logging
log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(message)s")

# Load env
env_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]
for p in env_paths:
    if load_dotenv(p):
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
        break

# Configs
deluge_config = {
    "host": "localhost",
    "port": 58846,
    "username": "localclient",
    "password": os.getenv("DELUGE_PASSWORD"),
}
plex_config = {
    "url": os.getenv("PLEX_SERVER"),
    "token": os.getenv("PLEX_TOKEN"),
}
containers = ["vpn", "deluge", "plex-server", "radarr", "sonarr"]

# Docker availability

def docker_available():
    try:
        subprocess.check_output(["docker", "ps"], stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def check_container(name):
    if not docker_available():
        logging.warning("Docker not available — skipping container check.")
        return False
    try:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
        return result.stdout.strip() == "true"
    except:
        return False

# Plex monitoring

def check_plex_local():
    print("[DEBUG] Starting Plex test")
    try:
        print(f"[DEBUG] Connecting to Plex server at {plex_config['url']}")
        server = PlexServer(plex_config["url"], plex_config["token"])
        sessions = server.sessions()
        info_lines = []
        for session in sessions:
            media = session.media[0].parts[0].streams
            video_stream = next((s for s in media if s.streamType == 1), None)
            audio_stream = next((s for s in media if s.streamType == 2), None)
            resolution = getattr(session, 'videoResolution', 'Unknown')
            transcode = getattr(session, 'transcode', None)
            transcode_status = 'Yes' if transcode else 'No'
            info_lines.append(f"User: {session.user.title}, Client: {session.player.title}, File: {session.title}, Video: {video_stream.codec if video_stream else 'N/A'}, {resolution}, Audio: {audio_stream.codec if audio_stream else 'N/A'}, Transcode: {transcode_status}")

        plex_proc = next((p for p in psutil.process_iter(['name']) if 'plex' in p.info['name'].lower()), None)
        cpu = plex_proc.cpu_percent(interval=1) if plex_proc else 'N/A'
        mem = plex_proc.memory_info().rss / (1024 * 1024) if plex_proc else 'N/A'
        temp_dir = "/transcode"
        free_space = psutil.disk_usage(temp_dir).free / (1024 * 1024 * 1024) if os.path.exists(temp_dir) else 'N/A'

        info_lines.append(f"CPU: {cpu}% | RAM: {mem}MB | Temp FS Free: {free_space}GB")
        info_lines.append(f"Clients: {len(sessions)}")
        send_discord_message("\n".join(info_lines))
        return True
    except Exception as e:
        print(f"[DEBUG] Plex connection failed: {e}")
        return False

# Run all checks

def run_all_checks():
    print("[DEBUG] Starting Deluge and network tests")
    results = {
        "plex": check_plex_local(),
        "deluge_active": False,
        "deluge_ip_match": False,
        "radarr_sonarr": False,
        "all_containers": False
    }

    try:
        client = DelugeRPCClient(**deluge_config, decode_utf8=False)
        client.connect()
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        results["deluge_active"] = any(t[b"state"] in (b"Downloading", b"Seeding") for t in torrents.values())
        print(f"[DEBUG] Deluge active: {results['deluge_active']}")
    except Exception as e:
        print(f"[DEBUG] Deluge check failed: {e}")

    deluge_ip, vpn_ip, has_net = None, None, False
    try:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "deluge", "core.conf"))
        with open(path, "r") as f:
            for line in f:
                if '"outgoing_interface"' in line:
                    match = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', line)
                    deluge_ip = match.group(1)
                    break
        print(f"[DEBUG] Deluge config IP: {deluge_ip}")
    except Exception as e:
        print(f"[DEBUG] Failed to read Deluge config: {e}")

    try:
        result = subprocess.run(["docker", "exec", "vpn", "ip", "addr", "show", "tun0"], capture_output=True, text=True)
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        vpn_ip = match.group(1) if match else None
        print(f"[DEBUG] VPN IP: {vpn_ip}")
    except Exception as e:
        print(f"[DEBUG] Failed to get VPN IP: {e}")

    try:
        result = subprocess.run(["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        has_net = result.returncode == 0
        print(f"[DEBUG] Deluge internet access: {has_net}")
    except Exception as e:
        print(f"[DEBUG] Deluge internet check failed: {e}")

    results["deluge_ip_match"] = deluge_ip and vpn_ip and deluge_ip == vpn_ip and has_net
    print("[DEBUG] Starting Radarr/Sonarr/container checks")
    results["radarr_sonarr"] = check_container("radarr") and check_container("sonarr")
    results["all_containers"] = all(check_container(c) for c in containers)

    return results

# Execute and report
print("[DEBUG] Running full check suite")
status = run_all_checks()
failures = [k for k, v in status.items() if not v]

if not status.get("plex"):
    logging.info("SEV 0: Plex not responding locally.")
    send_discord_message("[SEV 0] Plex access failure detected.")
if not status.get("deluge_active"):
    logging.info("SEV 1: Deluge not active.")
    send_discord_message("[SEV 1] Deluge idle — diagnostic triggered.")
if not status.get("deluge_ip_match"):
    logging.info("SEV 1: Deluge VPN/IP/Net mismatch.")
    send_discord_message("[SEV 1] Deluge IP mismatch or no internet.")
if not status.get("radarr_sonarr"):
    logging.info("SEV 2: Radarr or Sonarr not responding.")
    send_discord_message("[SEV 2] Radarr/Sonarr failure.")
if not status.get("all_containers"):
    logging.info("SEV 3: One or more containers down.")
    send_discord_message("[SEV 3] Container failure.")

if failures:
    send_discord_message(f"[INFO] Some checks failed: {', '.join(failures)}")
else:
    duration = round(time.time() - start_time, 2)
    send_discord_message(f"[OK] All services operational. Runtime: {duration}s")
