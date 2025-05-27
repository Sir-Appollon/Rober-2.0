# ===============================
# OLD CODE BLOCK — PRESERVED
# ===============================
# (Full code block previously written has been commented out for reference)
# [... entire previous implementation was here ...]

# ===============================
# REACTIVATED PLEX TEST VERSION
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

# Plex test (accessibility, session count, transcode)
PLEX_URL = os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
print("[DEBUG - run_quick_check.py] Connecting to Plex")
plex_msg_lines = []
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    sessions = plex.sessions()
    session_count = len(sessions)
    plex_msg_lines.append(f"[PLEX STATUS] Active sessions: {session_count}")
    print(f"[DEBUG] Plex active session count: {session_count}")

    transcode_count = 0
    for session in sessions:
        try:
            if hasattr(session, 'transcodeSession') and session.transcodeSession:
                transcode_count += 1
        except Exception as e:
            print(f"[DEBUG] Transcode check failed on session: {e}")

    if transcode_count > 0:
        plex_msg_lines.append(f"[INFO] {transcode_count} session(s) using transcoding")
    else:
        plex_msg_lines.append("[INFO] No transcoding in use")

    # Local accessibility test
    print("[DEBUG - run_quick_check.py] Testing local access to Plex with curl")
    try:
        response = subprocess.run([
            "curl", "-s", "--max-time", "5", f"{PLEX_URL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if response.returncode == 0:
            plex_msg_lines.append("[LOCAL ACCESS] Plex accessible locally")
        else:
            plex_msg_lines.append("[LOCAL ACCESS] Plex NOT accessible locally")
    except Exception as e:
        plex_msg_lines.append(f"[LOCAL ACCESS] Plex local test failed: {e}")

    # External accessibility test skipped — would require external IP or DNS
    plex_msg_lines.append("[EXTERNAL ACCESS] External check requires external IP/domain")

    for line in plex_msg_lines:
        print(f"[DEBUG] {line}")
    send_msg("\n".join(plex_msg_lines))

except Exception as e:
    print(f"[DEBUG] Plex session fetch failed: {e}")
    send_msg(f"[CRITICAL ERROR] Plex access failed: {e}")
