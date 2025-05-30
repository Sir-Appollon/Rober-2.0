#!/usr/bin/env python3

import subprocess
import time
import re
import json
import os

config_path = "/config/deluge/core.conf"  # Chemin correct depuis le conteneur configurateur


def system_has_internet():
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", "https://api.ipify.org"],
            capture_output=True, text=True
        )
        ip = result.stdout.strip()
        return re.match(r"\d+\.\d+\.\d+\.\d+", ip) is not None
    except Exception:
        return False


def vpn_has_internet():
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", "https://api.ipify.org"],
            capture_output=True, text=True
        )
        ip = result.stdout.strip()
        if re.match(r"\d+\.\d+\.\d+\.\d+", ip):
            print(f"[VPN] OK - IP publique VPN : {ip}")
            return ip
    except Exception as e:
        print(f"[VPN] Erreur de connexion : {e}")
    return None


def wait_for_vpn_with_retry(max_attempts=5, delay=15):
    for attempt in range(1, max_attempts + 1):
        print(f"[VPN] Vérification {attempt}/{max_attempts} de la connectivité...")
        vpn_ip = vpn_has_internet()
        if vpn_ip:
            return vpn_ip

        if system_has_internet():
            print(f"[VPN] L'hôte a Internet mais pas le VPN. Attente {delay}s avant nouvelle tentative...")
        else:
            print("[VPN] L'hôte n'a pas accès à Internet non plus. Nouvelle tentative après délai...")
        time.sleep(delay)

    raise RuntimeError("[ERROR] Le VPN n'a pas d'accès Internet après plusieurs essais.")


def update_deluge_ip(new_ip):
    print(f"[INFO] Mise à jour du fichier core.conf avec l'adresse IP {new_ip}...")
    with open(config_path, 'r') as f:
        config = json.load(f)

    existing_ip = config.get("listen_interface", "")
    if existing_ip == new_ip:
        print("[INFO] IP déjà présente, aucune modification nécessaire.")
        return

    config["listen_interface"] = new_ip
    config["outgoing_interface"] = new_ip

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print("[INFO] Fichier core.conf mis à jour avec succès.")


if __name__ == "__main__":
    print("[INFO] Script lancé depuis le conteneur VPN.")
    vpn_ip = wait_for_vpn_with_retry(max_attempts=5, delay=15)
    update_deluge_ip(vpn_ip)
    print("[SUCCESS] Deluge est prêt à être relancé avec l'IP VPN.")
