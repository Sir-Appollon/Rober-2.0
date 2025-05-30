#!/usr/bin/env python3

import subprocess
import time
import re
import json
import os
import sys

config_path = "/config/core.conf"  # depuis l'intérieur du conteneur deluge

def system_has_internet():
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", "https://api.ipify.org"],
            capture_output=True, text=True
        )
        ip = result.stdout.strip()
        return re.match(r"\d+\.\d+\.\d+\.\d+", ip) is not None
    except Exception as e:
        print(f"[ERROR] Test Internet (host) échoué : {e}")
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
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        raise RuntimeError(f"[ERROR] Impossible de lire {config_path} : {e}")

    existing_ip = config.get("listen_interface", "")
    if existing_ip == new_ip:
        print("[INFO] IP déjà présente, aucune modification nécessaire.")
        return

    config["listen_interface"] = new_ip
    config["outgoing_interface"] = new_ip

    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print("[INFO] Fichier core.conf mis à jour avec succès.")
    except Exception as e:
        raise RuntimeError(f"[ERROR] Impossible d’écrire dans {config_path} : {e}")


if __name__ == "__main__":
    print("[INFO] Script de configuration Deluge lancé.")
    try:
        vpn_ip = wait_for_vpn_with_retry(max_attempts=5, delay=15)
        update_deluge_ip(vpn_ip)
        print("[SUCCESS] Configuration Deluge OK avec IP VPN.")
    except Exception as e:
        print(str(e))
        sys.exit(1)  # ← empêchera Deluge de démarrer en cas d’erreur
