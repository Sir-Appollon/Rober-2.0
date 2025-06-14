#!/usr/bin/env python3

import subprocess
import time
import re
import os

# Chemin vers le core.conf depuis le host
config_path = "../../config/deluge/core.conf"


def stop_deluge():
    print("[INFO] Arrêt de Deluge...")
    subprocess.run(
        ["docker", "stop", "deluge"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_deluge():
    print("[INFO] Redémarrage de Deluge...")
    subprocess.run(
        ["docker", "start", "deluge"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def is_deluge_running():
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", "name=deluge"], capture_output=True, text=True
    )
    return result.stdout.strip() != ""


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


def update_deluge_ip_in_config(new_ip):
    print(f"[INFO] Mise à jour du fichier core.conf avec l'IP {new_ip}...")
    try:
        with open(config_path, "r") as f:
            lines = f.readlines()

        new_lines = []
        has_listen = has_outgoing = False
        for line in lines:
            if '"listen_interface"' in line:
                new_lines.append(f'  "listen_interface": "{new_ip}",\n')
                has_listen = True
            elif '"outgoing_interface"' in line:
                new_lines.append(f'  "outgoing_interface": "{new_ip}",\n')
                has_outgoing = True
            else:
                new_lines.append(line)

        if not has_listen:
            new_lines.insert(-1, f'  "listen_interface": "{new_ip}",\n')
        if not has_outgoing:
            new_lines.insert(-1, f'  "outgoing_interface": "{new_ip}",\n')

        with open(config_path, "w") as f:
            f.writelines(new_lines)

        print("[INFO] Mise à jour du core.conf réussie.")
    except Exception as e:
        raise RuntimeError(f"[ERREUR] Échec de la mise à jour du core.conf : {e}")


if __name__ == "__main__":
    print("[SCRIPT] Début du script de configuration IP Deluge depuis VPN")

    if is_deluge_running():
        stop_deluge()
        time.sleep(2)

    vpn_ip = get_vpn_internal_ip()
    update_deluge_ip_in_config(vpn_ip)

    start_deluge()

    print("[SUCCESS] IP mise à jour et Deluge relancé.")
