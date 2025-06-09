"""
File: monitor_loop.py
Purpose: Periodically triggers the run_quick_check.py script to assess system health.

Inputs:
- None directly. Indirectly depends on the output of /app/run_quick_check.py.

Outputs:
- Triggers /app/run_quick_check.py every 10 minutes.
- Does not store or log outputs unless debug mode is enabled.

Triggered Files/Services:
- Executes run_quick_check.py located in core/
"""

import time
import subprocess
import os
import importlib.util

# Interval between checks in seconds (10 minutes)
INTERVAL_SECONDS = 120

# Set mode to "debug" to enable verbose output
mode = "nomral"  # Change to "debug" for debug mode

# Discord notifier setup
discord_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),
]

send_discord_message = None

for discord_path in discord_paths:
    if os.path.isfile(discord_path):
        try:
            spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
            discord_notify = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord_notify)
            send_discord_message = discord_notify.send_discord_message
            break
        except Exception:
            pass

if send_discord_message:
    send_discord_message("[INFO] monitor_loop.py started")


def run_quick_check():
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Executing run_quick_check.py via subprocess")

    result = subprocess.run(
    ["python3", "/app/run_quick_check.py"],  # ← Chemin corrigé
    capture_output=True,
    text=True
)
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Subprocess output:")
        print(result.stdout.strip())

    return "FAILURE" in result.stdout

def alerts_plex():
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Executing alerts_plex.py via subprocess")

    result = subprocess.run(
    ["python3", "/app/alerts/alerts_plex.py"],  # ← Chemin corrigé
    capture_output=True,
    text=True
)
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Subprocess output:")
        print(result.stdout.strip())

    return "FAILURE" in result.stdout

if __name__ == "__main__":
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Starting monitor loop with interval:", INTERVAL_SECONDS)

    while True:
        run_quick_check()
        time.sleep(INTERVAL_SECONDS)
