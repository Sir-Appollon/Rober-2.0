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

INTERVAL_SECONDS = 240
mode = "debug"

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
        try:
            spec = importlib.util.spec_from_file_location(
                "discord_notify", discord_path
            )
            discord_notify = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord_notify)
            send_discord_message = discord_notify.send_discord_message
            break
        except Exception as e:
            if mode == "debug":
                print(f"[DEBUG] Failed to import Discord notifier: {e}")

if send_discord_message:
    send_discord_message("[INFO] monitor_loop.py started")


def run_quick_check():
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Executing run_quick_check.py via subprocess")

    result = subprocess.run(
        ["python3", "/app/run_quick_check.py"], capture_output=True, text=True
    )

    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Subprocess output:")
        print(result.stdout.strip())

    return "FAILURE" in result.stdout


def alerts():
    if mode == "debug":
        print("[DEBUG - alerts.py] Executing alerts.py via subprocess")

    result = subprocess.run(
        ["python3", "/app/alerts/alerts.py"], capture_output=True, text=True
    )

    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Subprocess output:")
        print(result.stdout.strip())

    return "FAILURE" in result.stdout


def repair():
    if mode == "debug":
        print("[DEBUG - repair.py] Executing repairr.py via subprocess")

    result = subprocess.run(
        ["python3", "/app/repair/repair.py"], capture_output=True, text=True
    )

    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Subprocess output:")
        print(result.stdout.strip())

    return "FAILURE" in result.stdout


if __name__ == "__main__":
    if mode == "debug":
        print(
            "[DEBUG - monitor_loop.py] Starting monitor loop with interval:",
            INTERVAL_SECONDS,
        )

    while True:
        run_quick_check()
        alerts()
        repair()
        time.sleep(INTERVAL_SECONDS)
