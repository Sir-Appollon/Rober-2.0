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
            resolution = getattr(session, 'videoResolution', 'Unknown')
            transcode = getattr(session, 'transcode', None)
            transcode_status = 'Yes' if transcode else 'No'
            info_lines.append(f"User: {session.user.title}, Client: {session.player.title}, File: {session.title}, \
Video: {video_stream.codec if video_stream else 'N/A'}, {resolution}, \
Audio: {audio_stream.codec if audio_stream else 'N/A'}, Transcode: {transcode_status}")

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
