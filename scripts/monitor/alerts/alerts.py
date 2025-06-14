import json
import subprocess
import time
import os
import importlib.util

LOG_FILE = "/mnt/data/system_monitor_log.json"
ALERT_STATE_FILE = "/mnt/data/alert_state.json"
PLEX_SERVICE_NAME = "plex-server"

# Chargement du module Discord
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


# Fichier état des alertes
def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f)


# fct test
def start_alert_sequence():
    print("[ALERTE] Début de la séquence d’alerte.")
    if send_discord_message:
        send_discord_message(
            "[ALERTE] 📡 Début de la séquence de surveillance et d’alerte."
        )


# Lecture du dernier log JSON
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


# Vérifie l'accès local à Plex
def check_plex_local_access(data):
    plex = data.get("plex", {})
    local_access = plex.get("local_access", False)
    print(f"[DEBUG] local_access = {local_access}")
    return local_access is True or local_access == "yes"


# Vérifie l'accès externe à Plex
def check_plex_external_access(data):
    plex = data.get("plex", {})
    external_access = plex.get("external_access", False)
    print(f"[DEBUG] external_access = {external_access}")
    return external_access is True or external_access == "yes"


# Redémarre le conteneur Plex
def restart_plex():
    print("[ACTION] Redémarrage de Plex...")
    # subprocess.run(["docker", "restart", PLEX_SERVICE_NAME])
    if send_discord_message:
        send_discord_message(
            "[ALERTE] Plex a été redémarré automatiquement (local access failed)."
        )


# Lance un script de reconnexion pour Plex
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
            "[INFO] Tentative de reconnexion de Plex (via diagnostique en ligne)."
        )


# Vérifie la connectivité Internet depuis l'hôte (ou conteneur si adapté)
def check_plex_internet_connectivity():
    try:
        result = subprocess.run(
            ["ping", "-c", "2", "8.8.8.8"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            print("[ALERTE] Plex semble ne pas avoir d'accès Internet (ping échoué).")
            if send_discord_message:
                send_discord_message(
                    "[ALERTE] Plex ne semble plus avoir d'accès Internet."
                )
            return False
        else:
            print("[OK] Plex a accès à Internet.")
            return True
    except Exception as e:
        print(f"[ERROR] Échec de vérification Internet Plex: {e}")
        return False


# Vérifie si le débit Deluge est nul avec gestion d’état
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
        f"[DEBUG] Débit Deluge - Download: {download_kbps} kB/s, Upload: {upload_kbps} kB/s"
    )

    if send_discord_message:
        send_discord_message(
            f"[INFO] Débit Deluge : {download_kbps:.2f} kB/s ↓ | {upload_kbps:.2f} kB/s ↑"
        )

    if current_state == "inactive" and last_state != "inactive":
        print("[ALERTE] Deluge passe en inactif.")
        if send_discord_message:
            send_discord_message(
                "[ALERTE - initial] Deluge semble inactif : aucun trafic entrant ou sortant détecté."
            )
    elif current_state == "active" and last_state == "inactive":
        print("[ALERTE] Fin d'inactivité Deluge.")
        if send_discord_message:
            send_discord_message(
                "[ALERTE - initial] Deluge est redevenu actif : fin de l’événement."
            )

    state["deluge_status"] = current_state
    save_alert_state(state)


# Fonction principale de surveillance
def main():
    print("[MONITOR] Surveillance en cours...")
    start_alert_sequence()
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

    check_plex_internet_connectivity()
    check_deluge_activity(data)


if __name__ == "__main__":
    main()
