#!/usr/bin/env python3

import json
import subprocess
import time
import os

config_path = "../config/deluge/core.conf"  # Replace with actual path

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
        config = json.load(f)

    config['listen_interface'] = new_ip
    config['outgoing_interface'] = new_ip

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

if __name__ == "__main__":
    if is_deluge_running():
        print("Deluge is running. Stopping it...")
        stop_deluge()
        time.sleep(2)

    ip = ask_for_ip()
    update_deluge_ip(ip)
    print(f"Updated Deluge config with IP {ip}. Starting Deluge...")
    start_deluge()
