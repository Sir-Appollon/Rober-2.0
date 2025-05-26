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

# Interval between checks in seconds (10 minutes)
INTERVAL_SECONDS = 600

# Set mode to "debug" to enable verbose output
mode = "normal"  # Change to "debug" for debug mode

def run_quick_check():
    if mode == "debug":
        print("[DEBUG - monitor_loop.py] Executing run_quick_check.py via subprocess")

    result = subprocess.run(
        ["python3", "/app/scripts/core/run_quick_check.py"],
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
