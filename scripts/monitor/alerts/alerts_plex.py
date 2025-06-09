import json
import subprocess
import time
import os

LOG_FILE = "/mnt/data/system_monitor_log.json"
PLEX_SERVICE_NAME = "plex-server"

def read_latest_data():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
            return logs[-1]
    except Exception as e:
        print(f"[ERROR] Impossible de lire les données : {e}")
        return None

def check_plex_local_access(data):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", "no")
    return local_access == "yes"

def check_plex_local_access(data):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", "no")
    return local_access == "yes"

def check_plex_external_acess(data):
    plex = data.get("plex", {})
    external_access = plex.get("external_access", "no")   

def restart_plex():
    print("[ACTION] Redémarrage de Plex...")
    subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])

def main():
    print("[MONITOR] Surveillance en cours...")
    data = read_latest_data()
    if data is None:
        return

    if not check_plex_local_access(data):
        print("[ALERTE] Plex est inaccessible localement.")
        restart_plex()
    else:
        print("[OK] Plex est accessible localement.")

    if not check_plex_external_acess(data):
        print("[ALERTE] Plex est inaccessible localement.")
    else:
        print("[OK] Plex est accessible localement.")

if __name__ == "__main__":
    main()
