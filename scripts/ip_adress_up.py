#!/usr/bin/env python3

import subprocess
import time
import re

config_path = "../config/deluge/core.conf"

def stop_deluge():
    subprocess.run(["docker", "stop", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_deluge():
    subprocess.run(["docker", "start", "deluge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def is_deluge_running():
    result = subprocess.run(["docker", "ps", "-q", "-f", "name=deluge"], capture_output=True, text=True)
    return result.stdout.strip() != ""

def get_vpn_ip():
    result = subprocess.run(
        ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
        capture_output=True, text=True
    )
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
    if match:
        return match.group(1)
    else:
        raise RuntimeError("Could not detect VPN IP on tun0 inside container")

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

    ip = get_vpn_ip()
    update_deluge_ip(ip)
    print(f"Updated Deluge config with VPN IP {ip}. Starting Deluge...")
    start_deluge()
