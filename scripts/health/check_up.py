import os
import subprocess
import json
from dotenv import load_dotenv

# Charger les variables d'environnement
if not load_dotenv("/app/.env"):
    load_dotenv("../.env")

# Récupérer la variable ROOT
root_path = os.getenv("ROOT")

if not root_path:
    raise ValueError("La variable d'environnement ROOT n'est pas définie dans le fichier .env")

# Lire le fichier de log
log_file = "/mnt/data/system_monitor_log.json"

with open(log_file, "r") as f:
    logs = json.load(f)

last_entry = logs[-1]

vpn_ips = last_entry["network"].get("vpn_ip", [])
deluge_ips = last_entry["network"].get("deluge_ip", [])

ip_match = any(ip in vpn_ips for ip in deluge_ips)

if not ip_match:
    print("[ALERT] IP mismatch. Launching correction script...")
    subprocess.run(["python3", f"{root_path}/scripts/tool/ip_adress_up.py"])
else:
    print("[INFO] Deluge IPs match VPN IPs.")
