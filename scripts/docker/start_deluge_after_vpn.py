#!/usr/bin/env python3

import subprocess
import time
import re
import os

config_path = "/config/core.conf"

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
        time.sleep(delay)
    raise RuntimeError("[ERROR] Le VPN n'a pas d'accès Internet après plusieurs essais.")

def update_config_ip(ip):
    print(f"[INFO] Mise à jour du fichier core.conf avec l'adresse IP {ip}...")
    try:
        with open(config_path, 'r') as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if '"listen_interface"' in line:
                line = f'    "listen_interface": "{ip}",\n'
            elif '"outgoing_interface"' in line:
                line = f'    "outgoing_interface": "{ip}",\n'
            new_lines.append(line)

        # Ajoute les lignes si elles n'existaient pas
        if not any('"listen_interface"' in l for l in new_lines):
            new_lines.insert(-1, f'    "listen_interface": "{ip}",\n')
        if not any('"outgoing_interface"' in l for l in new_lines):
            new_lines.insert(-1, f'    "outgoing_interface": "{ip}",\n')

        with open(config_path, 'w') as f:
            f.writelines(new_lines)

        print("[INFO] Fichier core.conf mis à jour avec succès.")
    except Exception as e:
        raise RuntimeError(f"[ERROR] Impossible de modifier le fichier core.conf : {e}")

if __name__ == "__main__":
    print("[INFO] Script de configuration Deluge lancé.")
    vpn_ip = wait_for_vpn_with_retry()
    update_config_ip(vpn_ip)
    print("[SUCCESS] Script terminé.")
