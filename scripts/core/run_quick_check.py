import os
import sys
import subprocess
import logging
import time
import psutil
import shutil
from dotenv import load_dotenv
from plexapi.server import PlexServer
import importlib.util

mode = "debug"
discord_connected = False
print("[DEBUG - run_quick_check.py - INIT - 1] Script initiated")

# Setup Discord
print("[DEBUG - run_quick_check.py - INIT - 2] Initializing Discord connection")
discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

def send_msg(msg):
    global discord_connected
    try:
        send_discord_message(msg)
        discord_connected = True
        return True
    except Exception as e:
        print(f"[DEBUG - run_quick_check.py - Discord - Error] Discord message failed: {e}")
        return False

# Load .env
print("[DEBUG - run_quick_check.py - ENV - 1] Attempting to load .env")
env_loaded = False
for p in [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]:
    if load_dotenv(p):
        print(f"[DEBUG - run_quick_check.py - ENV - 2] Loaded environment file: {p}")
        env_loaded = True
        break
if not env_loaded:
    print("[DEBUG - run_quick_check.py - ENV - 3] No .env file found.")
else:
    print("[DEBUG - run_quick_check.py - ENV - 4] Environment variables loaded successfully")

# Plex test
print("[DEBUG - run_quick_check.py - PLEX - 1] Starting PLEX test suite")
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
plex_msg_lines = []

try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    print("[DEBUG - run_quick_check.py - PLEX - 2] Connected to Plex")

    sessions = plex.sessions()
    session_count = len(sessions)
    print(f"[DEBUG - run_quick_check.py - PLEX - 3] Active Plex sessions: {session_count}")
    plex_msg_lines.append(f"[PLEX STATUS] Active sessions: {session_count}")

    transcode_count = 0
    for session in sessions:
        try:
            media_title = session.title
            user = session.user.title
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

    # Local access check
    response = subprocess.run(["curl", "-s", "--max-time", "5", f"{PLEX_URL}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if response.returncode == 0:
        plex_msg_lines.append("[LOCAL ACCESS] Plex accessible locally")
    else:
        plex_msg_lines.append("[LOCAL ACCESS] Plex NOT accessible locally")

    plex_msg_lines.append("[EXTERNAL ACCESS] External check requires external IP/domain")

    # Plex process usage
    for proc in psutil.process_iter(['name', 'cmdline']):
        if 'plex' in ' '.join(proc.info.get('cmdline', [])).lower():
            try:
                cpu = proc.cpu_percent(interval=1)
                mem = proc.memory_percent()
                plex_msg_lines.append(f"[PROCESS] Plex CPU usage: {cpu:.2f}% | RAM usage: {mem:.2f}%")
            except:
                pass
            break

    # Transcode temp space
    try:
        usage = shutil.disk_usage("/transcode")
        free_gb = usage.free / (1024**3)
        plex_msg_lines.append(f"[DISK] /transcode free space: {free_gb:.2f} GB")
    except:
        plex_msg_lines.append("[DISK] /transcode folder not found")

    for line in plex_msg_lines:
        print(f"[DEBUG - run_quick_check.py - PLEX - INFO] {line}")
    send_msg("\n".join(plex_msg_lines))

except Exception as e:
    print(f"[DEBUG - run_quick_check.py - PLEX - ERROR] Plex session fetch failed: {e}")
    send_msg(f"[CRITICAL ERROR] Plex access failed: {e}")

if discord_connected:
    print("[DEBUG - run_quick_check.py - DISCORD - SUCCESS] Discord message sent successfully")
else:
    print("[DEBUG - run_quick_check.py - DISCORD - FAIL] No Discord message sent")
