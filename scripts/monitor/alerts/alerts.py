import json
import subprocess
import time
import os
import importlib.util

LOG_FILE = "/mnt/data/system_monitor_log.json"
PLEX_SERVICE_NAME = "plex-server"

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
    send_discord_message("[INFO] alert.py started")

def read_latest_data():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
            latest = logs[-1]
            print(f"[DEBUG] Données JSON lues : {json.dumps(latest, indent=2)}")
            return latest
    except Exception as e:
        print(f"[ERROR] Impossible de lire les données : {e}")
        return None

def check_plex_local_access(data):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", "no")
    return local_access == "yes"

def check_plex_external_access(data):  # <-- Corrected typo in function name
    plex = data.get("plex", {})
    external_access = plex.get("external_access", "no")
    return external_access == "yes"

def restart_plex():
    print("[ACTION] Redémarrage de Plex...")
#    subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])
    if send_discord_message:
        send_discord_message("[ALERTE] Plex a été redémarré automatiquement (local access failed).")

def reconnect_plex():
    print("[ACTION] Reconnect Plex...")
    subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])
    if send_discord_message:
        send_discord_message("[INFO] Tentative de reconnexion de Plex (external access).")

def main():
    print("[MONITOR] Surveillance en cours...")
    data = read_latest_data()
    if data is None:
        return

    if not check_plex_local_access(data):
        print("[ALERTE] Plex est inaccessible localement.")
        if send_discord_message:
            send_discord_message("[ALERTE] Perte d'accès local à Plex détectée.")
        restart_plex()
    else:
        print("[OK] Plex est accessible localement.")

    if not check_plex_external_access(data):
        print("[ALERTE] Plex est inaccessible depuis l'extérieur.")
        if send_discord_message:
            send_discord_message("[ALERTE] Perte d'accès externe à Plex détectée.")
    else:
        print("[OK] Plex est accessible depuis l'extérieur.")

if __name__ == "__main__":
    main()
