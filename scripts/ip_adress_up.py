#!/usr/bin/env python3

import json

config_path = "../config/deluge/core.conf"  # Replace with actual path


def ask_for_ip():
    return input("Enter new VPN IP: ").strip()


def update_deluge_ip(new_ip):
    with open(config_path, "r") as f:
        config = json.load(f)

    config["listen_interface"] = new_ip
    config["outgoing_interface"] = new_ip

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


if __name__ == "__main__":
    ip = ask_for_ip()
    update_deluge_ip(ip)
    print(f"Deluge config updated with IP {ip}")
