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

discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(message)s")

env_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]
env_loaded = False
for p in env_paths:
    if load_dotenv(p):
        env_loaded = True
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
        break
if not env_loaded:
    print("[DEBUG - run_quick_check.py] No .env file found.")

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
        running = result.stdout.strip() == "true"
        if mode == "debug":
            print(f"[DEBUG - check_container] Container '{name}' running: {running}")
        return running
    except:
        return False

def check_plex_local():
    try:
        if mode == "debug":
            print(f"[DEBUG - check_plex_local] Checking Plex connection at {plex_config['url']}")
        server = PlexServer(plex_config["url"], plex_config["token"])
        sessions = server.sessions()
        info_lines = []
        for session in sessions:
            media = session.media[0].parts[0].streams
            video_stream = next((s for s in media if s.streamType == 1), None)
            audio_stream = next((s for s in media if s.streamType == 2), None)
            info_lines.append(f"User: {session.user.title}, Client: {session.player.title}, File: {session.title}, \
Video: {video_stream.codec if video_stream else 'N/A'}, {session.videoResolution}, \
Audio: {audio_stream.codec if audio_stream else 'N/A'}, Transcode: {'Yes' if session.transcode else 'No'}")

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
        if mode == "debug":
            print(f"[DEBUG - check_plex_local] Plex connection failed: {e}")
        return False

def check_deluge_activity():
    try:
        client = DelugeRPCClient(**deluge_config, decode_utf8=False)
        client.connect()
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        active = any(t[b"state"] in (b"Downloading", b"Seeding") for t in torrents.values())
        if mode == "debug":
            print(f"[DEBUG - check_deluge_activity] Deluge active: {active}, States: {[t[b'state'] for t in torrents.values()]}")
        return active
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - check_deluge_activity] Deluge RPC failed: {e}")
        return False

def get_deluge_config_ip():
    try:
        path = "/app/config/deluge/core.conf"
        if not os.path.exists(path):
            path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "deluge", "core.conf"))
        with open(path, "r") as f:
            for line in f:
                if '"outgoing_interface"' in line:
                    match = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', line)
                    if match:
                        ip = match.group(1)
                        if mode == "debug":
                            print(f"[DEBUG - get_deluge_config_ip] Outgoing IP from config: {ip}")
                        return ip
        return None
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - get_deluge_config_ip] Failed to read Deluge config: {e}")
        return None

def get_vpn_ip():
    try:
        result = subprocess.run(["docker", "exec", "vpn", "ip", "addr", "show", "tun0"], capture_output=True, text=True)
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        ip = match.group(1) if match else None
        if mode == "debug":
            print(f"[DEBUG - get_vpn_ip] VPN IP: {ip}")
        return ip
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - get_vpn_ip] Failed to get VPN IP: {e}")
        return None

def deluge_can_access_internet():
    try:
        result = subprocess.run(["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok = result.returncode == 0
        if mode == "debug":
            print(f"[DEBUG - deluge_can_access_internet] Deluge internet access: {ok}")
        return ok
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - deluge_can_access_internet] Deluge internet test failed: {e}")
        return False

def get_cpu_temp():
    try:
        out = subprocess.check_output(["sensors"]).decode()
        for line in out.splitlines():
            if "Package id 0" in line or "Core 0" in line:
                return line.strip()
    except:
        return "Unavailable"

def get_hdd_temp():
    try:
        result = subprocess.run(["sudo", "hddtemp", "/dev/sda"], capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "Unavailable"

def get_disk_usage():
    return psutil.disk_usage("/").percent

def get_docker_uptimes():
    try:
        out = subprocess.check_output("docker ps --format '{{.Names}} {{.RunningFor}}'", shell=True).decode().strip()
        return out
    except:
        return "Unavailable"

def check_all():
    data = [
        f"CPU Temp: {get_cpu_temp()}",
        f"HDD Temp: {get_hdd_temp()}",
        f"Disk Usage: {get_disk_usage()}%",
        f"Docker Uptime: {get_docker_uptimes()}"
    ]
    send_discord_message("\n".join(data))

if not check_plex_local():
    logging.info("SEV 0: Plex not responding locally.")
    send_discord_message("[SEV 0] Plex access failure detected.")
    # subprocess.run(["python3", "./SEV/Ident/sev0.py"])
    print("FAILURE")
    exit()
elif not check_deluge_activity():
    logging.info("SEV 1: Deluge not active.")
    send_discord_message("[SEV 1] Deluge idle — diagnostic triggered.")
    print("FAILURE")
    # subprocess.run(["python3", "./SEV/Ident/sev1.py"])
    exit()
else:
    deluge_ip = get_deluge_config_ip()
    vpn_ip = get_vpn_ip()
    has_net = deluge_can_access_internet()

    if not deluge_ip or not vpn_ip or deluge_ip != vpn_ip or not has_net:
        logging.info("SEV 1: Deluge VPN/IP/Net mismatch.")
        debug_details = f"Deluge IP: {deluge_ip}, VPN IP: {vpn_ip}, Internet OK: {has_net}"
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] SEV1 trigger details: {debug_details}")
        send_discord_message(f"[SEV 1] Deluge IP mismatch or no internet.\n{debug_details}")
        print("FAILURE")
        # subprocess.run(["python3", "./SEV/Ident/sev1.py"])
        exit()

    if not all(check_container(c) for c in ["radarr", "sonarr"]):
        logging.info("SEV 2: Radarr or Sonarr not responding.")
        send_discord_message("[SEV 2] Radarr/Sonarr failure.")
        print("FAILURE")
        # subprocess.run(["python3", "./SEV/Ident/sev2.py"])
        exit()

    if not all(check_container(c) for c in containers):
        logging.info("SEV 3: One or more containers down.")
        send_discord_message("[SEV 3] Container failure.")
        print("FAILURE")
        # subprocess.run(["python3", "./SEV/Ident/sev3.py"])
        exit()

    duration = round(time.time() - start_time, 2)
    send_discord_message(f"[OK] All services operational. Runtime: {duration}s")
    check_all()
