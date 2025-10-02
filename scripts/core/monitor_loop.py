#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_loop.py (orchestrateur périodique)

Rôle:
- Appelle périodiquement:
  1) run_quick_check.py (si présent)
  2) monitor_repair.py --alerts (évalue et met à jour alert_state)
  3) monitor_repair.py --deluge-verify  (+ AUTO: déclenche plex si offline selon cooldown)

Config via ENV (valeurs par défaut entre parenthèses):
- LOOP_INTERVAL_SECONDS (60)            : délai entre les cycles
- STEP_DELAY_SECONDS (20)               : délai entre les étapes d’un même cycle
- MONITOR_REPAIR (/app/scripts/monitor/monitor_repair.py)
- QUICK_CHECK (/app/run_quick_check.py)
- MONITOR_LOG_FILE (/mnt/data/system_monitor_log.json)  : source des alerts
- ALERT_STATE_FILE (/mnt/data/alert_state.json)
- DISCORD_WEBHOOK (vide)                : si défini, envoie les logs “hauts-niveaux”
- DEBUG (1)                             : 1=verbose, 0=quiet
- LOG_PATH (/mnt/data/monitor_loop.log) : si défini, append des logs

Comportement:
- Si QUICK_CHECK n’existe pas → skip sans erreur.
- Si MONITOR_REPAIR n’existe pas → log + Discord + continue.
- Gestion SIGINT/SIGTERM pour sortir proprement.
"""

import os
import sys
import time
import json
import signal
import subprocess
from datetime import datetime
from pathlib import Path
import urllib.request

# ====== ENV / defaults ======
LOOP_INTERVAL_SECONDS = int(os.environ.get("LOOP_INTERVAL_SECONDS", "60"))
STEP_DELAY_SECONDS    = int(os.environ.get("STEP_DELAY_SECONDS", "20"))
MONITOR_REPAIR        = os.environ.get("MONITOR_REPAIR", "/app/scripts/monitor/monitor_repair.py")
QUICK_CHECK           = os.environ.get("QUICK_CHECK", "/app/run_quick_check.py")
MONITOR_LOG_FILE      = os.environ.get("MONITOR_LOG_FILE", "/mnt/data/system_monitor_log.json")
ALERT_STATE_FILE      = os.environ.get("ALERT_STATE_FILE", "/mnt/data/alert_state.json")
DISCORD_WEBHOOK       = os.environ.get("DISCORD_WEBHOOK", "").strip()
DEBUG                 = os.environ.get("DEBUG", "1") == "1"
LOG_PATH              = os.environ.get("LOG_PATH", "/mnt/data/monitor_loop.log")

RUN = True  # flag for signal handling

# ====== Logging + Discord ======
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

def dlog(msg):
    if DEBUG:
        log(f"[DEBUG] {msg}")

def send_discord(content: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": content[:1900]}).encode("utf-8")
        req = urllib.request.Request(DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        # On ne casse jamais la boucle à cause de Discord
        pass

# ====== Signals ======
def _handle_stop(signum, frame):
    global RUN
    log(f"Received signal {signum}. Stopping loop...")
    RUN = False

signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)

# ====== Subprocess helper ======
def run_cmd(cmd, title=None, cwd=None):
    if title:
        dlog(f"RUN {title}: {' '.join(cmd)} (cwd={cwd or os.getcwd()})")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        if DEBUG:
            if out:
                dlog(f"{title or 'cmd'} STDOUT:\n{out}")
            if err:
                dlog(f"{title or 'cmd'} STDERR:\n{err}")
        return res.returncode, out, err
    except FileNotFoundError as e:
        log(f"[ERROR] {title or 'cmd'} not found: {e}")
        send_discord(f"❌ monitor_loop: {title or 'cmd'} not found.")
        return 127, "", str(e)
    except Exception as e:
        log(f"[ERROR] {title or 'cmd'} exception: {e}")
        send_discord(f"❌ monitor_loop: {title or 'cmd'} exception: {e}")
        return 1, "", str(e)

# ====== Steps ======
def step_quick_check():
    """Lance /app/run_quick_check.py si présent."""
    if not Path(QUICK_CHECK).is_file():
        dlog(f"QUICK_CHECK not found at {QUICK_CHECK}; skipping.")
        return True
    rc, out, err = run_cmd(["python3", QUICK_CHECK], title="run_quick_check")
    # Convention: on considère OK si exit code 0 (peu importe le texte)
    return rc == 0

def step_alerts():
    """Lance monitor_repair.py --alerts avec le log défini."""
    if not Path(MONITOR_REPAIR).is_file():
        log(f"[ERROR] monitor_repair not found at {MONITOR_REPAIR}")
        send_discord("❌ monitor_loop: monitor_repair.py introuvable.")
        return False
    env = os.environ.copy()
    env["ALERT_STATE_FILE"] = ALERT_STATE_FILE
    rc, out, err = run_cmd(
        ["python3", MONITOR_REPAIR, "--alerts", "--alerts-from", MONITOR_LOG_FILE],
        title="alerts",
        cwd=str(Path(MONITOR_REPAIR).parent),
    )
    return rc == 0

def step_repair():
    """
    1) Vérifie/répare Deluge si 'inactive' (via alert_state) → --deluge-verify
    2) Laisse le mode AUTO de monitor_repair déclencher plex_online si 'offline' (sans forcer).
    """
    if not Path(MONITOR_REPAIR).is_file():
        log(f"[ERROR] monitor_repair not found at {MONITOR_REPAIR}")
        send_discord("❌ monitor_loop: monitor_repair.py introuvable.")
        return False
    # On lance explicitement la vérification Deluge; puis, sans flags supplémentaires,
    # monitor_repair.py regardera alert_state et *déclenchera* plex si offline/cooldown OK.
    rc, out, err = run_cmd(
        ["python3", MONITOR_REPAIR, "--deluge-verify"],
        title="repair-deluge-verify",
        cwd=str(Path(MONITOR_REPAIR).parent),
    )
    if rc != 0:
        return False
    # Appel sans flags → chemin AUTO (voir monitor_repair.py)
    rc2, out2, err2 = run_cmd(
        ["python3", MONITOR_REPAIR],
        title="repair-auto-plex",
        cwd=str(Path(MONITOR_REPAIR).parent),
    )
    # Même si rc2 != 0 (p.ex. rien à faire), on ne considère pas l'ensemble en échec.
    return rc2 in (0,)

# ====== Main loop ======
def main():
    log("monitor_loop started.")
    send_discord("🟢 monitor_loop: started.")

    while RUN:
        cycle_start = time.time()
        try:
            # 1) quick check (optionnel)
            dlog("Step: quick_check")
            step_quick_check()
            time.sleep(STEP_DELAY_SECONDS)

            # 2) alerts (met à jour alert_state.json)
            dlog("Step: alerts")
            ok_alerts = step_alerts()
            if not ok_alerts:
                log("[WARN] alerts step returned non-zero.")

            time.sleep(STEP_DELAY_SECONDS)

            # 3) repair (deluge verify + auto plex si offline)
            dlog("Step: repair")
            ok_repair = step_repair()
            if not ok_repair:
                log("[WARN] repair step returned non-zero.")

        except Exception as e:
            log(f"[ERROR] Unexpected exception in loop: {e}")
            send_discord(f"❌ monitor_loop: exception {e}")

        # Attendre jusqu’au prochain cycle (en tenant compte du temps écoulé)
        elapsed = time.time() - cycle_start
        sleep_left = max(0, LOOP_INTERVAL_SECONDS - int(elapsed))
        dlog(f"Cycle finished in {int(elapsed)}s. Sleeping {sleep_left}s.")
        for _ in range(sleep_left):
            if not RUN:
                break
            time.sleep(1)

    log("monitor_loop stopped.")
    send_discord("🟡 monitor_loop: stopped.")

if __name__ == "__main__":
    main()
