# ===============================
# OLD CODE BLOCK — PRESERVED
# ===============================
# (Full code block previously written has been commented out for reference)
# [... entire previous implementation was here ...]

# ===============================
# UPDATED FULL TESTING VERSION
# ===============================
import os
import sys
import subprocess
import logging
import time
from dotenv import load_dotenv
from plexapi.server import PlexServer
import importlib.util

mode = "debug"
print("[DEBUG - run_quick_check.py] Script initiated")

# Setup Discord
discord_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py"))
spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
discord_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_notify)
send_discord_message = discord_notify.send_discord_message

def send_msg(msg):
    try:
        send_discord_message(msg)
        return True
    except Exception as e:
        print(f"[DEBUG - run_quick_check.py] Discord message failed: {e}")
        return False

# Load .env
print("[DEBUG - run_quick_check.py] Attempting to load .env")
env_loaded = False
for p in [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]:
    if load_dotenv(p):
        print(f"[DEBUG - run_quick_check.py] Loaded environment file: {p}")
        env_loaded = True
        break
if not env_loaded:
    print("[DEBUG - run_quick_check.py] No .env file found.")

# Plex session count only
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
print("[DEBUG - run_quick_check.py] Connecting to Plex")
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    sessions = plex.sessions()
    session_count = len(sessions)
    print(f"[DEBUG] Plex active session count: {session_count}")
    send_msg(f"[PLEX STATUS] Active sessions: {session_count}")
except Exception as e:
    print(f"[DEBUG] Plex session fetch failed: {e}")
    send_msg(f"[CRITICAL ERROR] Plex access failed: {e}")
