#!/usr/bin/env python3

import subprocess
import time

config_path = "../config\deluge\core.conf"  # Replace with actual path

def stop_deluge():
    subprocess.run(["docker", "stop", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_deluge():
    subprocess.run(["docker", "start", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def is_deluge_running():
    result = subprocess.run(["docker", "ps", "-q", "-f", "name=deluge"], capture_output=True, text=True)
    return result.stdout.strip() != ""

def ask_for_ip():
    return input("Enter new VPN IP: ").strip()

def update_deluge_ip(new_ip):
    with open(config_path, 'r') as f:
        lines = f.readlines()

    with open(config_path, 'w') as f:
        for line in lines:
            if '"listen_interface"' in line:
                f.write(f'  "listen_interface": "{new_ip}",\n')
            elif '"outgoing_interface"' in line:
                f.write(f'  "outgoing_interface": "{new_ip}",\n')
            else:
                f.write(line)

if __name__ == "__main__":
    if is_deluge_running():
        print("Deluge is running. Stopping it...")
        stop_deluge()
        time.sleep(2)

    ip = ask_for_ip()
    update_deluge_ip(ip)
    print(f"Updated Deluge config with IP {ip}. Starting Deluge...")
    start_deluge()
