#!/usr/bin/env python3

import subprocess
import time
import re
import os
import json

config_path = "/config/core.conf"

def get_internal_vpn_ip():
    try:
        print("[INFO] Récupération IP VPN depuis tun0...")
        result = subprocess.run(
            ["ip", "addr", "show", "tun0"],
            capture_output=True, text=True
        )
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            ip = match.group(1)
            print(f"[VPN] IP locale VPN détectée : {ip}")
            return ip
        else:
            raise RuntimeError("Aucune IP trouvée sur tun0")
    except Exception as e:
        raise RuntimeError(f"[ERREUR] Impossible de détecter l'IP VPN : {e}")

def update_core_conf(ip):
    print(f"[INFO] Mise à jour de core.conf avec l'IP : {ip}")

    with open(config_path, "r") as f:
        config = json.load(f)

    updated = False
    if config.get("listen_interface") != ip:
        config["listen_interface"] = ip
        updated = True
    if config.get("outgoing_interface") != ip:
        config["outgoing_interface"] = ip
        updated = True

    if updated:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print("[INFO] Fichier core.conf mis à jour.")
    else:
        print("[INFO] Aucune modification nécessaire.")

if __name__ == "__main__":
    print("[SCRIPT] Configuration Deluge via IP VPN")
    time.sleep(10)  # Laisse le temps au VPN de démarrer
    try:
        vpn_ip = get_internal_vpn_ip()
        update_core_conf(vpn_ip)
    except Exception as e:
        print(f"[ERREUR] {e}")
    print("[SCRIPT] Terminé.")
