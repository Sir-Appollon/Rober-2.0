#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import importlib.util
import time

LOG_FILE = "/mnt/data/system_monitor_log.json"
ALERT_STATE_FILE = "/mnt/data/alert_state.json"

# ====== PARAMÈTRES (anti-flap) ======
LOCAL_FAILS_FOR_ALERT = int(os.getenv("LOCAL_FAILS_FOR_ALERT", "3"))
LOCAL_SUCCESSES_TO_CLEAR = int(os.getenv("LOCAL_SUCCESSES_TO_CLEAR", "2"))
EXTERNAL_FAILS_FOR_ALERT = int(os.getenv("EXTERNAL_FAILS_FOR_ALERT", "3"))
EXTERNAL_SUCCESSES_TO_CLEAR = int(os.getenv("EXTERNAL_SUCCESSES_TO_CLEAR", "2"))

# ====== DISCORD MODULE ======
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


# ====== STATE HELPERS ======
def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "plex_local": {"status": "unknown", "failure_streak": 0, "success_streak": 0},
        "plex_external": {"status": "unknown", "failure_streak": 0, "success_streak": 0},
        "deluge_status": "unknown",
    }

def save_alert_state(state):
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def read_latest_data():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
            if not logs:
                return None
            return logs[-1]
    except Exception as e:
        print(f"[ERROR] Unable to read data: {e}")
        return None


# ====== CHECKS ======
def check_plex_local(data, state):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", False)
    connected = plex.get("connected", False)

    is_up = bool(local_access) or bool(connected)
    node = state["plex_local"]
    prev_status = node.get("status", "unknown")

    if is_up:
        node["success_streak"] += 1
        node["failure_streak"] = 0
        if prev_status != "online" and node["success_streak"] >= LOCAL_SUCCESSES_TO_CLEAR:
            node["status"] = "online"
            print("[OK] Plex is accessible locally.")
            if send_discord_message and prev_status == "offline":
                send_discord_message("[ALERT - END] Plex local access restored.")
    else:
        node["failure_streak"] += 1
        node["success_streak"] = 0
        if prev_status != "offline" and node["failure_streak"] >= LOCAL_FAILS_FOR_ALERT:
            node["status"] = "offline"
            print("[ALERT] Plex local access lost.")
            if send_discord_message:
                send_discord_message("[ALERT - initial] Plex local access lost (after consecutive failures).")

    state["plex_local"] = node


def check_plex_external(data, state):
    plex = data.get("plex", {})
    external_access = str(plex.get("external_access", "")).lower()
    external_detail = str(plex.get("external_detail", ""))

    is_up = (external_access == "yes")
    node = state["plex_external"]
    prev_status = node.get("status", "unknown")

    if is_up:
        node["success_streak"] += 1
        node["failure_streak"] = 0
        if prev_status != "online" and node["success_streak"] >= EXTERNAL_SUCCESSES_TO_CLEAR:
            node["status"] = "online"
            print("[OK] Plex is accessible externally.")
            if send_discord_message and prev_status == "offline":
                send_discord_message("[ALERT - END] Plex is online from outside.")
    else:
        node["failure_streak"] += 1
        node["success_streak"] = 0
        if prev_status != "offline" and node["failure_streak"] >= EXTERNAL_FAILS_FOR_ALERT:
            node["status"] = "offline"
            print("[ALERT] Plex external access lost.")
            if send_discord_message:
                if "via_ip_ok" in external_detail:
                    send_discord_message("[ALERT - initial] External DNS resolution appears broken (fallback IP works).")
                elif external_access == "error":
                    send_discord_message(f"[ALERT] Plex external check error: {external_detail}")
                else:
                    send_discord_message("[ALERT - initial] Plex appears offline from outside (after consecutive failures).")

    state["plex_external"] = node


def check_deluge(data, state):
    deluge = data.get("deluge", {})
    download_kbps = deluge.get("download_rate_kbps", 0.0)
    upload_kbps = deluge.get("upload_rate_kbps", 0.0)

    current_state = "inactive" if download_kbps == 0.0 and upload_kbps == 0.0 else "active"
    last_state = state.get("deluge_status")

    if current_state == "inactive" and last_state != "inactive":
        print("[ALERT] Deluge has become inactive.")
        if send_discord_message:
            send_discord_message("[ALERT - initial] Deluge appears inactive: no traffic detected.")
    elif current_state == "active" and last_state == "inactive":
        print("[OK] Deluge is active again.")
        if send_discord_message:
            send_discord_message("[ALERT - END] Deluge is active again.")

    state["deluge_status"] = current_state


# ====== MAIN ======
def main():
    print("[MONITOR] Monitoring in progress...")
    data = read_latest_data()
    if data is None:
        return

    state = load_alert_state()
    check_plex_external(data, state)
    check_plex_local(data, state)
    check_deluge(data, state)
    save_alert_state(state)


if __name__ == "__main__":
    main()
