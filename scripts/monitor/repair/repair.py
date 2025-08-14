#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import os
import re
import importlib.util
from dotenv import load_dotenv

# --- Chemins & config ---
ALERT_STATE_FILE = "/mnt/data/alert_state.json"
CONFIG_PATH = "/app/config/deluge/core.conf"
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
load_dotenv(dotenv_path)

send_discord_message = None


# =========================
#  Discord (optionnel)
# =========================
def setup_discord():
    """Initialise l'envoi Discord si discord_notify.py est présent."""
    global send_discord_message
    discord_paths = [
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")
        ),
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")
        ),
    ]
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
                # On reste silencieux si Discord n'est pas dispo
                pass


# =========================
#  Utilitaires
# =========================
def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def run_and_send_on_fail(cmd, title="Task"):
    """
    Exécute un script externe et :
      - envoie un court message Discord si succès
      - en cas d'échec, envoie le tail (stdout+stderr) tronqué dans un bloc code
    """
    res = subprocess.run(cmd, capture_output=True, text=True)

    if send_discord_message:
        if res.returncode == 0:
            send_discord_message(f"[OK] {title} terminé avec succès.")
        else:
            out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
            tail = out[-1800:] if out else "(aucune sortie)"
            send_discord_message(
                f"[ERROR] {title} a échoué (exit={res.returncode}).\n```log\n{tail}\n```"
            )

    return res.returncode


# =========================
#  Deluge – vérif & réparation IP
# =========================
def get_vpn_internal_ip():
    print("[INFO] Retrieving internal VPN IP (tun0)...")
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            ip = match.group(1)
            print(f"[VPN] Local VPN IP detected: {ip}")
            return ip
        else:
            raise RuntimeError("No IP detected on interface tun0")
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed to detect internal VPN IP: {e}")


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
        raise RuntimeError(f"[ERROR] Failed to read core.conf: {e}")


def verify_interface_consistency():
    vpn_ip = get_vpn_internal_ip()
    config_ips = extract_interface_ips_from_config()

    print(f"[DEBUG] VPN IP = {vpn_ip}")
    print(f"[DEBUG] core.conf listen_interface = {config_ips['listen_interface']}")
    print(f"[DEBUG] core.conf outgoing_interface = {config_ips['outgoing_interface']}")

    consistent = (
        config_ips["listen_interface"] == vpn_ip
        and config_ips["outgoing_interface"] == vpn_ip
    )
    return consistent, vpn_ip, config_ips


def launch_repair_deluge_ip():
    print("[ACTION] Launching Deluge repair procedure...")
    if send_discord_message:
        send_discord_message("[ACTION] Starting Deluge IP repair…")
    code = run_and_send_on_fail(
        ["python3", "/app/repair/ip_adress_up.py"], "Deluge IP repair"
    )
    if code == 0:
        print("[OK] ip_adress_up.py executed successfully")
    else:
        print(f"[ERROR] ip_adress_up.py exit {code}")


def handle_deluge_verification():
    state = load_alert_state()
    if state.get("deluge_status") != "inactive":
        # Rien à faire si Deluge n'était pas marqué inactif
        return

    print("[INFO] Deluge was marked as inactive in previous state.")
    if send_discord_message:
        send_discord_message("[ALERT - test] Deluge appears inactive: validating the issue.")

    try:
        consistent, vpn_ip, config_ips = verify_interface_consistency()

        if not consistent:
            print("[CONFIRMED] Inconsistent IP: triggering repair.")
            if send_discord_message:
                send_discord_message("[ALERT - confirmation] Deluge is inactive: mismatched IP address.")
            launch_repair_deluge_ip()
            if send_discord_message:
                send_discord_message(f"[ALERT - repair complete] IP address updated: {vpn_ip}")
        else:
            print("[INFO] IPs are consistent, no repair needed.")
    except Exception as e:
        print(f"[ERROR] Secondary verification failed: {e}")
        if send_discord_message:
            send_discord_message(f"[ERROR] Verification failed: {str(e)}")


# =========================
#  Plex – exécution directe de la réparation
# =========================
def launch_repair_plex():
    print("[ACTION] Launching Plex repair procedure...")
    if send_discord_message:
        send_discord_message("[ACTION] Starting Plex repair…")
    code = run_and_send_on_fail(
        ["python3", "/app/repair/repair_plex.py"], "Plex repair"
    )
    if code == 0:
        print("[OK] repair_plex.py executed successfully")
    else:
        print(f"[ERROR] repair_plex.py exit {code}")


# =========================
#  Main
# =========================
def main():
    print("[DEBUG] repair.py is running")
    setup_discord()
    handle_deluge_verification()  # répare Deluge si nécessaire
    launch_repair_plex()          # lance toujours la réparation Plex


if __name__ == "__main__":
    main()
