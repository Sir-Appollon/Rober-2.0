#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import os
import re
import time
import importlib.util
import argparse
from dotenv import load_dotenv

ALERT_STATE_FILE = "/mnt/data/alert_state.json"
CONFIG_PATH = "/app/config/deluge/core.conf"
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
load_dotenv(dotenv_path)

# Cooldown en secondes entre deux tests Plex (pour éviter les boucles)
PLEX_TEST_COOLDOWN = int(os.getenv("PLEX_TEST_COOLDOWN", "300"))  # 5 min par défaut

send_discord_message = None

# ===== Discord setup =====
def setup_discord():
    global send_discord_message
    discord_paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "discord", "discord_notify.py")),
    ]
    for discord_path in discord_paths:
        if os.path.isfile(discord_path):
            try:
                spec = importlib.util.spec_from_file_location("discord_notify", discord_path)
                discord_notify = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(discord_notify)
                send_discord_message = discord_notify.send_discord_message
                break
            except Exception:
                pass

# ===== Helpers =====
def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_alert_state(state):
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def run_and_send(cmd, title="Task"):
    """Run a script, send result to Discord (logs truncated)."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    if send_discord_message:
        if res.returncode == 0:
            send_discord_message(f"[OK] {title} completed.\n```log\n{output[-1800:]}\n```")
        else:
            send_discord_message(f"[ERROR] {title} failed (exit={res.returncode}).\n```log\n{output[-1800:]}\n```")
    return res.returncode

# ===== Deluge repair =====
def get_vpn_internal_ip():
    result = subprocess.run(
        ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
        capture_output=True, text=True
    )
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
    if match:
        return match.group(1)
    raise RuntimeError("No IP detected on interface tun0")

def extract_interface_ips_from_config():
    with open(CONFIG_PATH, "r") as f:
        content = f.read()
    listen = re.search(r'"listen_interface"\s*:\s*"([^"]+)"', content)
    outgoing = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', content)
    return {
        "listen_interface": listen.group(1) if listen else None,
        "outgoing_interface": outgoing.group(1) if outgoing else None,
    }

def verify_interface_consistency():
    vpn_ip = get_vpn_internal_ip()
    config_ips = extract_interface_ips_from_config()
    consistent = (
        config_ips["listen_interface"] == vpn_ip
        and config_ips["outgoing_interface"] == vpn_ip
    )
    return consistent, vpn_ip, config_ips

def launch_repair_deluge_ip():
    if send_discord_message:
        send_discord_message("[ACTION] Starting Deluge IP repair…")
    return run_and_send(["python3", "/app/repair/ip_adress_up.py"], "Deluge IP repair")

def handle_deluge_verification():
    state = load_alert_state()
    if state.get("deluge_status") != "inactive":
        return
    if send_discord_message:
        send_discord_message("[ALERT] Deluge appears inactive: validating…")
    consistent, vpn_ip, _ = verify_interface_consistency()
    if not consistent:
        if send_discord_message:
            send_discord_message("[CONFIRMED] IP mismatch: repairing Deluge.")
        launch_repair_deluge_ip()
        if send_discord_message:
            send_discord_message(f"[DONE] Deluge IP updated to {vpn_ip}")
    else:
        print("[INFO] Deluge IPs consistent, no repair needed.")

# ===== Plex ONLINE test =====
def should_run_plex_online_test(force=False):
    if force:
        return True
    state = load_alert_state()
    status = state.get("plex_external_status")  # "online" | "offline" | None
    if status != "offline":
        return False
    now = time.time()
    last = state.get("plex_last_test_ts", 0)
    if (now - last) < PLEX_TEST_COOLDOWN:
        return False
    return True

def launch_plex_online_test():
    if send_discord_message:
        send_discord_message("[ACTION] Running Plex online test…")
    rc = run_and_send(["python3", "/app/repair/plex_online.py"], "Plex online test")
    state = load_alert_state()
    state["plex_last_test_ts"] = time.time()
    save_alert_state(state)
    return rc

# ===== Main =====
def main():
    print("[DEBUG] repair.py is running")
    setup_discord()

    # === Parse des arguments ===
    parser = argparse.ArgumentParser(description="Health/repair orchestrator")
    parser.add_argument("--deluge-verify", action="store_true",
                        help="Vérifier/réparer Deluge si nécessaire")
    parser.add_argument("--deluge-repair", action="store_true",
                        help="Forcer la réparation IP de Deluge")
    parser.add_argument("--plex-online", action="store_true",
                        help="Lancer le test Plex online")
    parser.add_argument("--force", action="store_true",
                        help="Ignorer les conditions et cooldowns (utilisé avec --plex-online)")
    parser.add_argument("--all", action="store_true",
                        help="Lancer tous les tests et réparations disponibles")
    args = parser.parse_args()

    # === Exécution selon flags ===
    if args.all:
        handle_deluge_verification()
        if should_run_plex_online_test(force=True):
            launch_plex_online_test()
        return

    if args.deluge_verify:
        handle_deluge_verification()

    if args.deluge_repair:
        launch_repair_deluge_ip()

    if args.plex_online:
        if should_run_plex_online_test(force=args.force):
            launch_plex_online_test()
        else:
            print("[INFO] Plex online test skipped (status not offline or cooldown).")

if __name__ == "__main__":
    main()
