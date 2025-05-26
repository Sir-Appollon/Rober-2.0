"""
File: run_quick_check.py
Purpose: Perform system service validations, IP integrity checks, and collect diagnostics.

Triggers:
- SEV 0: Plex local access failure
- SEV 1: Deluge idle, IP mismatch, or no internet
- SEV 2: Radarr/Sonarr down
- SEV 3: Other container failure

Outputs:
- Logs to /mnt/data/entry_log_quick_check.log
- Sends Discord notifications
"""

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

# DEBUG MODE
mode = "debug"
start_time = time.time()

# Load Discord notifier
discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

# Logging
log_file = "/mnt/data/entry_log_quick_check.log"
logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(message)s")

# Load environment
env_paths = ["/app/.env", "../.env"]
env_loaded = False
for p in env_paths:
    if load_dotenv(p):
        env_loaded = True
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
        break
if not env_loaded:
    print("[DEBUG - run_quick_check.py] No .env file found.")

# Configuration
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

# Utility functions
def docker_available():
    try:
        subprocess.check_output(["docker", "ps"], stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def run_sev(code):
    sev_paths = {
        "SEV0": "./SEV/Ident/sev0.py",
        "SEV1": "./SEV/Ident/sev1.py",
        "SEV2": "./SEV/Ident/sev2.py",
        "SEV3": "./SEV/Ident/sev3.py"
    }
    path = sev_paths.get(code)
    if path and os.path.exists(path):
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Running SEV script: {path}")
        subprocess.run(["python3", path])
    else:
        logging.warning(f"{code} script not found at {path}")
        send_discord_message(f"[{code}] Diagnostic script missing: {path}")
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] {code} script not found at {path}")

def check_container(name):
    if not docker_available():
        logging.warning("Docker not available — skipping container check.")
        return False
    try:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                                capture_output=True, text=True)
        running = result.stdout.strip() == "true"
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Container '{name}' running: {running}")
        return running
    except:
        return False

def check_all_containers():
    return all(check_container(c) for c in containers)

def check_plex_local():
    try:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Checking Plex connection at {plex_config['url']}")
        PlexServer(plex_config["url"], plex_config["token"])
        return True
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Plex connection failed: {e}")
        return False

def check_deluge_activity():
    try:
        client = DelugeRPCClient(**deluge_config, decode_utf8=False)
        client.connect()
        torrents = client.call("core.get_torrents_status", {}, ["state"])
        active = any(t[b"state"] in (b"Downloading", b"Seeding") for t in torrents.values())
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Deluge active: {active}")
        return active
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Deluge RPC failed: {e}")
        return False

def check_radarr_sonarr():
    return check_container("radarr") and check_container("sonarr")

def get_deluge_config_ip(path="/app/config/deluge/core.conf"):
    try:
        with open(path, "r") as f:
            config = json.load(f)
            ip = config.get("outgoing_interface")
            if mode == "debug":
                print(f"[DEBUG - run_quick_check.py] Deluge config IP: {ip}")
            return ip
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Failed to read Deluge config: {e}")
        return None

def get_vpn_ip():
    if not docker_available():
        return None
    try:
        result = subprocess.run(["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
                                capture_output=True, text=True)
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        ip = match.group(1) if match else None
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] VPN IP: {ip}")
        return ip
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Failed to get VPN IP: {e}")
        return None

def deluge_can_access_internet():
    if not docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "exec", "deluge", "curl", "-s", "--max-time", "5", "https://www.google.com"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        ok = result.returncode == 0
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Deluge internet access: {ok}")
        return ok
    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Deluge internet test failed: {e}")
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
        result = subprocess.run(["sudo", "hddtemp", "/dev/sda"],
                                capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "Unavailable"

def get_disk_usage():
    return psutil.disk_usage("/").percent

def get_docker_uptimes():
    if not docker_available():
        return "Unavailable (no docker)"
    try:
        out = subprocess.check_output(
            "docker ps --format '{{.Names}} {{.RunningFor}}'",
            shell=True
        ).decode().strip()
        return out
    except:
        return "Unavailable"

# Main logic
if not check_plex_local():
    logging.info("SEV 0: Plex not responding locally.")
    send_discord_message("[SEV 0] Plex access failure detected.")
    run_sev("SEV0")
    print("FAILURE")
    exit()

elif not check_deluge_activity():
    logging.info("SEV 1: Deluge not active.")
    send_discord_message("[SEV 1] Deluge idle — diagnostic triggered.")
    run_sev("SEV1")
    print("FAILURE")
    exit()

else:
    deluge_ip = get_deluge_config_ip()
    vpn_ip = get_vpn_ip()
    has_net = deluge_can_access_internet()

    if not deluge_ip or not vpn_ip or deluge_ip != vpn_ip or not has_net:
        logging.info("SEV 1: Deluge VPN/IP/Net mismatch.")
        send_discord_message("[SEV 1] Deluge IP mismatch or no internet.")
        run_sev("SEV1")
        print("FAILURE")
        exit()

    elif not check_radarr_sonarr():
        logging.info("SEV 2: Radarr or Sonarr not responding.")
        send_discord_message("[SEV 2] Radarr/Sonarr failure.")
        run_sev("SEV2")
        print("FAILURE")
        exit()

    elif not check_all_containers():
        logging.info("SEV 3: One or more containers down.")
        send_discord_message("[SEV 3] Container failure.")
        run_sev("SEV3")
        print("FAILURE")
        exit()

    else:
        duration = round(time.time() - start_time, 2)
        cpu_temp = get_cpu_temp()
        hdd_temp = get_hdd_temp()
        disk_pct = get_disk_usage()
        uptime_info = get_docker_uptimes()
        logging.info("OK: All checks passed.")
        if mode == "debug":
            print(f"[DEBUG - run_quick_check.py] Run completed in {duration}s")
        send_discord_message("\n".join([
            "[OK] All services operational.",
            f"Disk Usage: {disk_pct}%",
            f"CPU Temp: {cpu_temp}",
            f"HDD Temp: {hdd_temp}",
            f"Docker Uptime:\n{uptime_info}",
            f"Execution Time: {duration}s"
        ]))
        print("OK")
