#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import os
import re
import time
import importlib.util
import argparse
from pathlib import Path

# ---------- Chargement .env robuste (avec ou sans python-dotenv) ----------
def _simple_parse_env(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # format KEY=VALUE (VALUE peut être "quoted" ou non)
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            env[k] = v
    except Exception:
        pass
    return env

def _try_load_with_dotenv(dotenv_path: Path) -> bool:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return False
    try:
        return load_dotenv(dotenv_path.as_posix())
    except Exception:
        return False

def _set_env_from_dict(d: dict):
    for k, v in d.items():
        # ne pas écraser des variables déjà définies dans l'env
        if k not in os.environ:
            os.environ[k] = v

def _search_upwards_for_env(start: Path, max_levels: int = 8) -> Path | None:
    cur = start.resolve()
    for _ in range(max_levels):
        candidate = cur / ".env"
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None

def load_env_robust():
    """
    Ordre de recherche:
    1) ${ROOT}/.env si ROOT défini
    2) ../../../.env relatif à ce fichier
    3) .env en remontant depuis ce fichier
    4) .env en remontant depuis le cwd
    """
    base_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []

    root = os.environ.get("ROOT")
    if root:
        candidates.append(Path(root) / ".env")

    # équivalent de l'ancien "../../../.env"
    candidates.append((base_dir / Path("../../../.env")).resolve())

    # remonte depuis le fichier
    found_from_file = _search_upwards_for_env(base_dir, max_levels=10)
    if found_from_file:
        candidates.append(found_from_file)

    # remonte depuis le cwd
    found_from_cwd = _search_upwards_for_env(Path.cwd(), max_levels=10)
    if found_from_cwd:
        candidates.append(found_from_cwd)

    # dédoublonne en gardant l'ordre
    uniq = []
    seen = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp not in seen:
            seen.add(rp)
            uniq.append(rp)

    for dotenv_path in uniq:
        if dotenv_path and dotenv_path.is_file():
            # Tente python-dotenv si dispo ; sinon parse simple
            if _try_load_with_dotenv(dotenv_path):
                print(f"[INFO] .env chargé (python-dotenv): {dotenv_path}")
                return
            parsed = _simple_parse_env(dotenv_path)
            if parsed:
                _set_env_from_dict(parsed)
                print(f"[INFO] .env chargé (parser interne): {dotenv_path}")
                return
    print("[INFO] Aucun .env trouvé/chargé (ou fichier vide).")

# Charger l'environnement le plus tôt possible
load_env_robust()

# ---------- Constantes & chemins ----------
ALERT_STATE_FILE = "/mnt/data/alert_state.json"
CONFIG_PATH = "/app/config/deluge/core.conf"

# Cooldown en secondes entre deux tests Plex (pour éviter les boucles)
PLEX_TEST_COOLDOWN = int(os.getenv("PLEX_TEST_COOLDOWN", "300"))  # 5 min par défaut

# Dérive tous les chemins depuis ce fichier
BASE_DIR = Path(__file__).resolve().parent
PLEX_ONLINE_SCRIPT = (BASE_DIR / "plex_online.py").as_posix()
DELUGE_IP_SCRIPT = (BASE_DIR / "ip_adress_up.py").as_posix()

send_discord_message = None

# ---------- Discord setup ----------
def setup_discord():
    """Essaie de charger send_discord_message depuis différents chemins probables."""
    global send_discord_message
    candidates = [
        (BASE_DIR / "discord" / "discord_notify.py"),
        (BASE_DIR.parent / "discord" / "discord_notify.py"),
        Path("/app/discord/discord_notify.py"),  # montage docker: - ${ROOT}/scripts/discord:/app/discord
    ]
    for discord_path in candidates:
        if discord_path.is_file():
            try:
                spec = importlib.util.spec_from_file_location("discord_notify", discord_path.as_posix())
                discord_notify = importlib.util.module_from_spec(spec)
                assert spec and spec.loader
                spec.loader.exec_module(discord_notify)  # type: ignore
                send_discord_message = getattr(discord_notify, "send_discord_message", None)
                if send_discord_message:
                    print(f"[INFO] Discord notify chargé depuis: {discord_path}")
                    return
            except Exception as e:
                print(f"[WARN] Échec chargement Discord notify: {discord_path} -> {e}")
    print("[INFO] Aucun module Discord trouvé, logs seulement en console.")

# ---------- Helpers ----------
def load_alert_state():
    try:
        if os.path.exists(ALERT_STATE_FILE):
            with open(ALERT_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_alert_state(state):
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def run_and_send(cmd, title="Task"):
    """Exécute une commande, miroite les logs en console et envoie sur Discord si dispo."""
    print(f"[RUN] {title}: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        msg = f"[ERROR] {title} introuvable: {e}"
        print(msg)
        if send_discord_message:
            send_discord_message(msg)
        return 127

    output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    tail = output[-1800:] if output else "(no output)"

    status = "OK" if res.returncode == 0 else f"ERROR({res.returncode})"
    print(f"[{status}] {title}\n----- LOG (tail) -----\n{tail}\n----------------------")

    if send_discord_message:
        if res.returncode == 0:
            send_discord_message(f"[OK] {title} completed.\n```log\n{tail}\n```")
        else:
            send_discord_message(f"[ERROR] {title} failed (exit={res.returncode}).\n```log\n{tail}\n```")

    return res.returncode

# ---------- Deluge repair ----------
def get_vpn_internal_ip():
    print("[INFO] Récupération IP interne VPN (tun0) depuis conteneur 'vpn'…")
    result = subprocess.run(
        ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
        capture_output=True, text=True
    )
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
    if match:
        ip = match.group(1)
        print(f"[INFO] IP VPN détectée: {ip}")
        return ip
    raise RuntimeError("Aucune IP détectée sur l'interface tun0")

def extract_interface_ips_from_config():
    print(f"[INFO] Lecture des interfaces dans {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        content = f.read()
    listen = re.search(r'"listen_interface"\s*:\s*"([^"]+)"', content)
    outgoing = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', content)
    ips = {
        "listen_interface": listen.group(1) if listen else None,
        "outgoing_interface": outgoing.group(1) if outgoing else None,
    }
    print(f"[INFO] Interfaces Deluge: {ips}")
    return ips

def verify_interface_consistency():
    vpn_ip = get_vpn_internal_ip()
    config_ips = extract_interface_ips_from_config()
    consistent = (
        config_ips["listen_interface"] == vpn_ip
        and config_ips["outgoing_interface"] == vpn_ip
    )
    print(f"[INFO] Cohérence IP Deluge/VPN: {consistent}")
    return consistent, vpn_ip, config_ips

def launch_repair_deluge_ip():
    if send_discord_message:
        send_discord_message("[ACTION] Starting Deluge IP repair…")
    return run_and_send(["python3", DELUGE_IP_SCRIPT], "Deluge IP repair")

def handle_deluge_verification():
    state = load_alert_state()
    if state.get("deluge_status") != "inactive":
        print("[INFO] Deluge non marqué 'inactive' → skip vérification.")
        return
    if send_discord_message:
        send_discord_message("[ALERT] Deluge appears inactive: validating…")
    consistent, vpn_ip, _ = verify_interface_consistency()
    if not consistent:
        if send_discord_message:
            send_discord_message("[CONFIRMED] IP mismatch: repairing Deluge.")
        rc = launch_repair_deluge_ip()
        if rc == 0 and send_discord_message:
            send_discord_message(f"[DONE] Deluge IP updated to {vpn_ip}")
    else:
        print("[INFO] Deluge IPs cohérentes, pas de réparation nécessaire.")

# ---------- Plex ONLINE test ----------
def should_run_plex_online_test(force=False):
    if force:
        print("[DECISION] Test Plex forcé → True")
        return True
    state = load_alert_state()
    status = state.get("plex_external_status")  # "online" | "offline" | None
    now = time.time()
    last = state.get("plex_last_test_ts", 0)
    print(f"[DECISION] plex_external_status={status}, now={now}, last={last}, cooldown={PLEX_TEST_COOLDOWN}")
    if status != "offline":
        print("[DECISION] Plex n'est pas 'offline' → skip test")
        return False
    if (now - last) < PLEX_TEST_COOLDOWN:
        print("[DECISION] Cooldown non expiré → skip test")
        return False
    print("[DECISION] Conditions réunies → lancer test Plex")
    return True

def launch_plex_online_test():
    if send_discord_message:
        send_discord_message("[ACTION] Running Plex online test…")
    rc = run_and_send(["python3", PLEX_ONLINE_SCRIPT], "Plex online test")
    state = load_alert_state()
    state["plex_last_test_ts"] = time.time()
    save_alert_state(state)
    return rc

# ---------- Main ----------
def main():
    print("[DEBUG] repair.py is running")
    setup_discord()

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
            print("[INFO] Plex online test skipped (status not offline ou cooldown).")

if __name__ == "__main__":
    main()
