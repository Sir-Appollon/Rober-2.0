import os
import subprocess
import logging
import sys
import re
import time
from dotenv import load_dotenv
from pathlib import Path
import sys

# Set your mode here
mode = "debug"  # change to "normal" to enable resolution functions

sys.path.append("..")
from discord_notify import send_discord_message

# Setup logging
log_file = "/mnt/data/sev1_resolution.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")

# Load .env
for path in ["/app/.env", "../.env", "../../.env"]:
    if Path(path).is_file():
        load_dotenv(dotenv_path=path)
        break

DELUGE_PASSWORD = os.getenv("DELUGE_PASSWORD")
DELUGE_CONFIG_PATH = "../config/deluge/core.conf"
VPN_CONTAINER = "vpn"
DELUGE_CONTAINER = "deluge"

def tail_logs(container, lines=5):
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container],
            capture_output=True, text=True
        )
        return result.stdout.strip().splitlines()[-1]
    except:
        return "[Log tail unavailable]"

def resolve_d001():
    log = tail_logs(VPN_CONTAINER)
    logging.error(f"[D-001 - Resolve Fail] VPN is down. Last log: {log}")
    send_discord_message(f"[D-001 - Resolution Failed] VPN is not running.\nLast log: {log}")

def resolve_d002():
    log = tail_logs(DELUGE_CONTAINER)
    logging.error(f"[D-002 - Resolve Fail] Deluge is down. Last log: {log}")
    send_discord_message(f"[D-002 - Resolution Failed] Deluge is not running.\nLast log: {log}")

def resolve_d003():
    try:
        subprocess.run(["docker", "restart", DELUGE_CONTAINER], check=True)
        logging.info("[D-003 - Resolve] Deluge restarted to fix RPC.")
        send_discord_message("[D-003 - Resolution Completed] Deluge restarted to restore RPC.")
    except Exception as e:
        logging.error(f"[D-003 - Resolve Fail] Could not restart Deluge. {str(e)}")
        send_discord_message(f"[D-003 - Resolution Failed] Deluge restart failed.")

def get_vpn_ip():
    result = subprocess.run(
        ["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "tun0"],
        capture_output=True, text=True
    )
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
    return match.group(1) if match else None

def update_deluge_ip(new_ip):
    with open(DELUGE_CONFIG_PATH, 'r') as f:
        lines = f.readlines()
    with open(DELUGE_CONFIG_PATH, 'w') as f:
        for line in lines:
            if '"listen_interface"' in line:
                f.write(f'  "listen_interface": "{new_ip}",\n')
            elif '"outgoing_interface"' in line:
                f.write(f'  "outgoing_interface": "{new_ip}",\n')
            else:
                f.write(line)

def stop_deluge():
    subprocess.run(["docker", "stop", DELUGE_CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_deluge():
    subprocess.run(["docker", "start", DELUGE_CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def resolve_d004():
    try:
        vpn_ip = get_vpn_ip()
        if not vpn_ip:
            raise Exception("Unable to fetch VPN IP.")
        stop_deluge()
        time.sleep(2)
        update_deluge_ip(vpn_ip)
        start_deluge()
        logging.info(f"[D-004 - Resolve] Updated Deluge config with VPN IP {vpn_ip}")
        send_discord_message(f"[D-004 - Resolution Completed] Deluge IP updated to {vpn_ip}")
    except Exception as e:
        logging.error(f"[D-004 - Resolve Fail] {str(e)}")
        send_discord_message(f"[D-004 - Resolution Failed] {str(e)}")


def resolve_d001():
    print("Resolving D-001...")

def resolve_d002():
    print("Resolving D-002...")

def resolve_d003():
    print("Resolving D-003...")

def resolve_d004():
    print("Resolving D-004...")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sev1_resolution.py D-00X")
        exit(1)

    code = sys.argv[1]

    if mode == "debug":
        print(f"[DEBUG MODE] Not executing resolution for {code}")
    elif mode == "normal":
        if code == "D-001":
            resolve_d001()
        elif code == "D-002":
            resolve_d002()
        elif code == "D-003":
            resolve_d003()
        elif code == "D-004":
            resolve_d004()
        else:
            print(f"Unknown code: {code}")
    else:
        print(f"Unknown mode: {mode}")
