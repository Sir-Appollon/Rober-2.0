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


def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f)


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


def check_plex_internet_local_connectivity():
    data = read_latest_data()
    if data is None:
        return

    plex = data.get("plex", {})
    local_access = plex.get("local_access", False)
    print(f"[DEBUG] local_access = {local_access}")

    if not (local_access is True or local_access == "yes"):
        print("[ALERT] Plex is not accessible locally.")
        if send_discord_message:
            send_discord_message("[ALERT] Local access to Plex lost.")
        # subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])
        if send_discord_message:
            send_discord_message(
                "[ALERT] Plex was automatically restarted (local access failed)."
            )
    else:
        print("[OK] Plex is accessible locally.")


def check_plex_internet_online_connectivity():
    data = read_latest_data()
    if data is None:
        return

    state = load_alert_state()

    plex = data.get("plex", {})
    external_access = plex.get("external_access", False)
    print(f"[DEBUG] external_access = {external_access}")

    if not (external_access is True or external_access == "yes"):
        print("[ALERT] Plex is not accessible externally.")
        if state.get("plex_external_status") != "offline":
            if send_discord_message:
                send_discord_message(
                    "[ALERT - initial] Plex appears to be offline : no connection from outside."
                )
            state["plex_external_status"] = "offline"
    else:
        print("[OK] Plex is accessible externally.")
        if state.get("plex_external_status") == "offline":
            if send_discord_message:
                send_discord_message("[ALERT - END] Plex is online")
            state["plex_external_status"] = "online"

    save_alert_state(state)


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


def main():
    print("[MONITOR] Monitoring in progress...")

    # Fetch shared data
    data = read_latest_data()
    if data is None:
        return

    # Core monitoring functions
    check_plex_internet_online_connectivity()
    check_plex_internet_local_connectivity()
    check_deluge_activity(data)


if __name__ == "__main__":
    main()
