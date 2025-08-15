#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair.py — Orchestrateur de santé/réparation

- Charge .env de façon robuste
- Peut vérifier/réparer Deluge (interfaces VPN)
- Peut lancer le test Plex externe (plex_online.py)
- Écrit/relit /mnt/data/alert_state.json pour l'état (offline/online) + cooldown

Nouveauté:
- Auto-déclenchement du test Plex si alert_state.json indique 'offline'
  même SANS --plex-online (optionnellement avec force si souhaité).
"""

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
        if k not in os.environ:
            os.environ[k] = v

def _search_upwards_for_env(start: Path, max_levels: int = 8):
    cur = start.resolve()
    for _ in range(max_levels):
        cand = cur / ".env"
        if cand.is_file():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return None

def load_env_robust():
    base_dir = Path(__file__).resolve().parent
    candidates = []

    root = os.environ.get("ROOT")
    if root:
        candidates.append(Path(root) / ".env")

    candidates.append((base_dir / Path("../../../.env")).resolve())

    f1 = _search_upwards_for_env(base_dir, 10)
    if f1: candidates.append(f1)

    f2 = _search_upwards_for_env(Path.cwd(), 10)
    if f2: candidates.append(f2)

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
            if _try_load_with_dotenv(dotenv_path):
                print(f"[INFO] .env chargé (python-dotenv): {dotenv_path}")
                return
            parsed = _simple_parse_env(dotenv_path)
            if parsed:
                _set_env_from_dict(parsed)
                print(f"[INFO] .env chargé (parser interne): {dotenv_path}")
                return
    print("[INFO] Aucun .env trouvé/chargé (ou fichier vide).")

load_env_robust()

# ---------- Constantes & chemins ----------
ALERT_STATE_FILE = "/mnt/data/alert_state.json"      # côté Docker (monté)
CONFIG_PATH = "/app/config/deluge/core.conf"         # côté Docker

# Cooldown (en secondes) entre deux tests Plex (évite les boucles)
PLEX_TEST_COOLDOWN = int(os.environ.get("PLEX_TEST_COOLDOWN", "300"))

# Si tu veux forcer l'auto-test même en cooldown (sans --force), mets à "1"
AUTO_PLEX_FORCE = os.environ.get("AUTO_PLEX_FORCE", "0") == "1"

BASE_DIR = Path(__file__).resolve().parent
send_discord_message = None

# ---------- Résolution des chemins de scripts appelés ----------
def _project_root_guess() -> Path | None:
    """Devine la racine du dépôt (si ROOT non défini)."""
    if os.environ.get("ROOT"):
        return Path(os.environ["ROOT"]).resolve()
    # remonter jusqu'à trouver un dossier 'scripts'
    cur = BASE_DIR
    for _ in range(8):
        if (cur / "scripts").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    # essai depuis cwd
    cur = Path.cwd().resolve()
    for _ in range(8):
        if (cur / "scripts").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None

def _first_existing(paths):
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            return pp.resolve()
    return None

def resolve_plex_online_script() -> Path | None:
    root = _project_root_guess()
    candidates = [
        BASE_DIR / "plex_online.py",                         # voisin de repair.py
        (root / "scripts/tool/plex_online.py") if root else None,   # host
        Path("/app/tool/plex_online.py"),                    # docker si bind ajouté
        Path("/app/monitor/repair/plex_online.py"),          # docker voisin
        Path("/app/repair/plex_online.py"),                  # docker core/repair
    ]
    return _first_existing([p for p in candidates if p])

def resolve_deluge_ip_script() -> Path | None:
    root = _project_root_guess()
    candidates = [
        BASE_DIR / "ip_adress_up.py",                        # voisin
        (root / "scripts/core/repair/ip_adress_up.py") if root else None,  # host
        Path("/app/repair/ip_adress_up.py"),                 # docker bind officiel
    ]
    return _first_existing([p for p in candidates if p])

# ---------- Discord setup ----------
def setup_discord():
    """Charge send_discord_message si dispo."""
    global send_discord_message
    root = _project_root_guess()
    candidates = [
        BASE_DIR / "discord" / "discord_notify.py",
        BASE_DIR.parent / "discord" / "discord_notify.py",
        (root / "scripts/discord/discord_notify.py") if root else None,  # host
        Path("/app/discord/discord_notify.py"),                          # docker
    ]
    for p in [c for c in candidates if c]:
        if p.is_file():
            try:
                spec = importlib.util.spec_from_file_location("discord_notify", p.as_posix())
                mod = importlib.util.module_from_spec(spec)
                assert spec and spec.loader
                spec.loader.exec_module(mod)  # type: ignore
                send_discord_message = getattr(mod, "send_discord_message", None)
                if send_discord_message:
                    print(f"[INFO] Discord notify chargé depuis: {p}")
                    return
            except Exception as e:
                print(f"[WARN] Échec chargement Discord notify: {p} -> {e}")
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

def run_and_send(cmd, title="Task", cwd: Path | None = None):
    """Exécute une commande, fixe le cwd vers le script cible, log console + Discord."""
    print(f"[RUN] {title}: {' '.join(cmd)} (cwd={cwd or Path.cwd()})")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd.as_posix() if cwd else None)
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
    script = resolve_deluge_ip_script()
    if not script:
        print("[ERROR] Deluge IP repair script introuvable.")
        return 127
    if send_discord_message:
        send_discord_message("[ACTION] Starting Deluge IP repair…")
    return run_and_send(["python3", script.as_posix()], "Deluge IP repair", cwd=script.parent)

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
    script = resolve_plex_online_script()
    if not script:
        print("[ERROR] plex_online.py introuvable dans les chemins connus. " +
              "Ajoute le bind '- ${ROOT}/scripts/tool:/app/tool' OU place le script à côté de repair.py.")
        return 127
    if send_discord_message:
        send_discord_message("[ACTION] Running Plex online test…")
    rc = run_and_send(["python3", script.as_posix()], "Plex online test", cwd=script.parent)
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

    # Mode batch "tout"
    if args.all:
        handle_deluge_verification()
        if should_run_plex_online_test(force=True):
            launch_plex_online_test()
        return

    # Exécutions ciblées via flags
    if args.deluge_verify:
        handle_deluge_verification()

    if args.deluge_repair:
        launch_repair_deluge_ip()

    if args.plex_online:
        if should_run_plex_online_test(force=args.force):
            launch_plex_online_test()
        else:
            print("[INFO] Plex online test skipped (status not offline ou cooldown).")

    # --- AUTO: lancer plex_online si le JSON indique un problème (sans --plex-online) ---
    # Ce bloc s'exécute même si aucun flag n'a été passé.
    # Il déclenche le test Plex si l'état est 'offline'. Par défaut, il respecte le cooldown.
    # Pour forcer en auto (ignorer cooldown), définir AUTO_PLEX_FORCE=1 dans l'env.
    ran_anything = any([args.all, args.deluge_verify, args.deluge_repair, args.plex_online])
    if not ran_anything:
        state = load_alert_state()
        if state.get("plex_external_status") == "offline":
            print("[AUTO] Plex est marqué 'offline' dans alert_state.json → lancement du test Plex")
            if should_run_plex_online_test(force=AUTO_PLEX_FORCE):
                launch_plex_online_test()
            else:
                print("[AUTO] Conditions non réunies (cooldown ou état) → test non lancé")

if __name__ == "__main__":
    main()
