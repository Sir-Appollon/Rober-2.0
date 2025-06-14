import json
import subprocess
import os
import re
import importlib.util

ALERT_STATE_FILE = "/mnt/data/alert_state.json"
CONFIG_PATH = "../../config/deluge/core.conf"

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


def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def get_vpn_internal_ip():
    print("[INFO] Récupération de l'IP interne du VPN (tun0)...")
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            ip = match.group(1)
            print(f"[VPN] IP VPN locale détectée : {ip}")
            return ip
        else:
            raise RuntimeError("Aucune IP détectée sur l'interface tun0")
    except Exception as e:
        raise RuntimeError(f"[ERREUR] Impossible de détecter l'IP VPN interne : {e}")


def extract_interface_ips_from_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()
            listen = re.search(r'"listen_interface"\s*:\s*"([^"]+)"', content)
            outgoing = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', content)
            return {
                "listen_interface": listen.group(1) if listen else None,
                "outgoing_interface": outgoing.group(1) if outgoing else None,
            }
    except Exception as e:
        raise RuntimeError(f"[ERREUR] Lecture core.conf échouée : {e}")


def verify_interface_consistency():
    vpn_ip = get_vpn_internal_ip()
    config_ips = extract_interface_ips_from_config()

    print(f"[DEBUG] VPN IP = {vpn_ip}")
    print(f"[DEBUG] core.conf listen_interface = {config_ips['listen_interface']}")
    print(f"[DEBUG] core.conf outgoing_interface = {config_ips['outgoing_interface']}")

    return (
        (
            config_ips["listen_interface"] == vpn_ip
            and config_ips["outgoing_interface"] == vpn_ip
        ),
        vpn_ip,
        config_ips,
    )


def launch_repair():
    print("[ACTION] Lancement de la procédure de réparation Deluge...")
    subprocess.run(["python3", "/app/repair/ip_adress_up.py"])


def main():
    state = load_alert_state()
    if state.get("deluge_status") == "inactive":
        print("[INFO] Deluge inactif détecté dans l’état précédent.")
        if send_discord_message:
            send_discord_message(
                "[ALERTE - test] Deluge semble inactif : validation de l'erreur."
            )

        try:
            consistent, vpn_ip, config_ips = verify_interface_consistency()

            if not consistent:
                print("[CONFIRMÉ] IP incohérente : déclenchement réparation.")
                if send_discord_message:
                    send_discord_message(
                        "[ALLERTE - confirmation] Deluge est inactif : IP adresse différente."
                    )
                    send_discord_message(
                        "[ALLERTE - réparation] Lancement du script de réparation Deluge..."
                    )
                launch_repair()
                if send_discord_message:
                    send_discord_message(
                        f"[ALLERTE - fin de réparation] Adresse IP mise à jour : {vpn_ip}"
                    )
            else:
                print("[INFO] IP cohérente, pas de réparation requise.")
        except Exception as e:
            print(f"[ERREUR] Échec de vérification secondaire : {e}")
            if send_discord_message:
                send_discord_message(f"[ERREUR] Vérification échouée : {str(e)}")


if __name__ == "__main__":
    main()
