#!/usr/bin/env python3

import subprocess
import time
import re
import json
import os

config_path = "../../config/deluge/core.conf"


def wait_for_container(container_name, timeout=60):
    print(f"[INFO] Attente du démarrage du conteneur '{container_name}'...")
    for _ in range(timeout):
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                                capture_output=True, text=True)
        if result.stdout.strip() == "true":
            print(f"[INFO] {container_name} est opérationnel.")
            return True
        time.sleep(1)
    raise TimeoutError(f"[ERROR] Timeout : {container_name} ne s'est pas lancé à temps.")


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
            ["docker", "exec", "vpn", "curl", "-s", "--max-time", "5", "https://api.ipify.org"],
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

    # Échec après tentatives → redémarrage du VPN
    print("[VPN] Échec après plusieurs tentatives. Redémarrage du conteneur VPN...")
    subprocess.run(["docker", "restart", "vpn"])
    time.sleep(10)

    vpn_ip = vpn_has_internet()
    if not vpn_ip:
        raise RuntimeError("[ERROR] Le VPN n'a toujours pas d'accès Internet après redémarrage.")
    return vpn_ip


def stop_deluge():
    print("[INFO] Arrêt du conteneur Deluge...")
    subprocess.run(["docker", "stop", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_deluge():
    print("[INFO] Redémarrage du conteneur Deluge...")
    subprocess.run(["docker", "start", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def update_deluge_ip(new_ip):
    print(f"[INFO] Mise à jour du fichier core.conf avec l'adresse IP {new_ip}...")
    with open(config_path, 'r') as f:
        config = json.load(f)

    config["listen_interface"] = new_ip
    config["outgoing_interface"] = new_ip

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print("[INFO] Fichier core.conf mis à jour avec succès.")


if __name__ == "__main__":
    print("[INFO] Conteneur VPN actif (le script est exécuté depuis celui-ci)")
    vpn_ip = wait_for_vpn_with_retry(max_attempts=5, delay=15)
    stop_deluge()
    time.sleep(2)
    update_deluge_ip(vpn_ip)
    start_deluge()
    print("[SUCCESS] Deluge redémarré avec la bonne IP VPN.")
