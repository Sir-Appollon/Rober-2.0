import json
import subprocess
import time
import os
import importlib.util

LOG_FILE = "/mnt/data/system_monitor_log.json"
ALERT_STATE_FILE = "/mnt/data/alert_state.json"
PLEX_SERVICE_NAME = "plex-server"

# Load Discord module
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
        except Exception:
            pass


# Alert state file
def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f)


# Test function
def start_alert_sequence():
    print("[ALERT] Alert sequence started.")
    if send_discord_message:
        send_discord_message("[ALERT] 📡 Monitoring and alert sequence started.")


# Read the latest JSON log
def read_latest_data():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
            latest = logs[-1]
            print(f"[DEBUG] JSON data read: {json.dumps(latest, indent=2)}")
            return latest
    except Exception as e:
        print(f"[ERROR] Unable to read data: {e}")
        return None


# Check Plex local access
def check_plex_local_access(data):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", False)
    print(f"[DEBUG] local_access = {local_access}")
    return local_access is True or local_access == "yes"


# Check Plex external access
def check_plex_external_access(data):
    plex = data.get("plex", {})
    external_access = plex.get("external_access", False)
    print(f"[DEBUG] external_access = {external_access}")
    return external_access is True or external_access == "yes"


# Restart the Plex container
def restart_plex():
    print("[ACTION] Restarting Plex...")
    # subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])
    if send_discord_message:
        send_discord_message(
            "[ALERT] Plex was automatically restarted (local access failed)."
        )


# Run reconnect script for Plex
def reconnect_plex():
    print("[ACTION] Reconnect Plex... (running plex_diagnostique_online.py)")
    try:
        result = subprocess.run(
            ["python3", "/app/alerts/plex_diagnostique_online.py"],
            capture_output=True,
            text=True,
        )
        print("[DEBUG] plex_diagnostique_online.py output:")
        print(result.stdout)
        if result.stderr:
            print("[DEBUG] Errors:")
            print(result.stderr)
    except Exception as e:
        print(f"[ERROR] Failed to run plex_diagnostique_online.py: {e}")

    if send_discord_message:
        send_discord_message(
            "[INFO] Attempting to reconnect Plex (via online diagnostics)."
        )


# Check Internet connectivity (from host or container)
def check_plex_internet_connectivity():
    try:
        result = subprocess.run(
            ["ping", "-c", "2", "8.8.8.8"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            print(
                "[ALERT - initial] Plex seems to have no Internet access (ping failed)."
            )
            if send_discord_message:
                send_discord_message(
                    "[ALERT - END] Plex appears to have lost Internet access."
                )
            return False
        else:
            print("[OK] Plex has Internet access.")
            return True
    except Exception as e:
        print(f"[ERROR] Failed to check Plex Internet connectivity: {e}")
        return False


# Check if Deluge speed is zero (with state handling)
def check_deluge_activity(data):
    state = load_alert_state()
    deluge = data.get("deluge", {})
    download_kbps = deluge.get("download_rate_kbps", None)
    upload_kbps = deluge.get("upload_rate_kbps", None)

    current_state = (
        "inactive" if download_kbps == 0.0 and upload_kbps == 0.0 else "active"
    )
    last_state = state.get("deluge_status")

    print(
        f"[DEBUG] Deluge Speed - Download: {download_kbps} kB/s, Upload: {upload_kbps} kB/s"
    )

    # if send_discord_message:
    #     send_discord_message(
    #         f"[INFO] Deluge speed: {download_kbps:.2f} kB/s ↓ | {upload_kbps:.2f} kB/s ↑"
    #     )

    if current_state == "inactive" and last_state != "inactive":
        print("[ALERT] Deluge has become inactive.")
        if send_discord_message:
            send_discord_message(
                "[ALERT - initial] Deluge appears to be inactive: no incoming or outgoing traffic detected."
            )
    elif current_state == "active" and last_state == "inactive":
        print("[ALERT] Deluge inactivity ended.")
        if send_discord_message:
            send_discord_message("[ALERT - END] Deluge is active again: event ended.")

    state["deluge_status"] = current_state
    save_alert_state(state)


# Main monitoring function
def main():
    print("[MONITOR] Monitoring in progress...")
    #    start_alert_sequence()
    data = read_latest_data()
    if data is None:
        return

    if not check_plex_local_access(data):
        print("[ALERT] Plex is not accessible locally.")
        if send_discord_message:
            send_discord_message("[ALERT] Local access to Plex lost.")
        restart_plex()
    else:
        print("[OK] Plex is accessible locally.")

    if not check_plex_external_access(data):
        print("[ALERT] Plex is not accessible externally.")
        if send_discord_message:
            send_discord_message("[ALERT] External access to Plex lost.")
    else:
        print("[OK] Plex is accessible externally.")

    check_plex_internet_connectivity()
    check_deluge_activity(data)


if __name__ == "__main__":
    main()
