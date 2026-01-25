#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_loop.py — orchestrateur périodique (adapté au docker-compose fourni)

Volumes pertinents dans le conteneur:
- /app            <= ${ROOT}/scripts/core
- /app/discord    <= ${ROOT}/scripts/discord
- /app/alerts     <= ${ROOT}/scripts/monitor/alerts (optionnel, non utilisé ici)
- /mnt/data       (persistant)

Commande lancée: ["python3", "/app/monitor_loop.py"]
"""

import os, sys, time, json, signal, subprocess, urllib.request
from pathlib import Path
from datetime import datetime
import importlib.util

# --------- .env fallback (au cas où) ----------
def _load_dotenv_simple(path):
    try:
        if not Path(path).is_file():
            return
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if not line or line.startswith("#"): 
                continue
            if "=" in line:
                k,v=line.split("=",1)
                k=k.strip(); v=v.strip().strip("'").strip('"')
                if k and k not in os.environ:
                    os.environ[k]=v
    except Exception:
        pass

# Essaye /app/.env (bind possible), puis ROOT/.env si exposé
_load_dotenv_simple("/app/.env")
if "ROOT" in os.environ:
    _load_dotenv_simple(os.path.join(os.environ["ROOT"], ".env"))

# --------- Config via ENV (défauts adaptés à /app) ----------
LOOP_INTERVAL_SECONDS = int(os.environ.get("LOOP_INTERVAL_SECONDS", "60"))   # délai entre cycles
STEP_DELAY_SECONDS    = int(os.environ.get("STEP_DELAY_SECONDS", "20"))      # délai entre étapes
MONITOR_REPAIR        = os.environ.get("MONITOR_REPAIR", "/app/monitor_repair.py")
QUICK_CHECK           = os.environ.get("QUICK_CHECK", "/app/run_quick_check.py")
MONITOR_LOG_FILE      = os.environ.get("MONITOR_LOG_FILE", "/mnt/data/system_monitor_log.json")
ALERT_STATE_FILE      = os.environ.get("ALERT_STATE_FILE", "/mnt/data/alert_state.json")
DISCORD_WEBHOOK       = os.environ.get("DISCORD_WEBHOOK", "").strip()
DEBUG                 = os.environ.get("DEBUG", "1") == "1"
LOG_PATH              = os.environ.get("LOG_PATH", "/mnt/data/monitor_loop.log")

RUN = True

# --------- Discord notify (module OU webhook direct) ----------
def _discord_via_webhook(msg: str) -> bool:
    if not DISCORD_WEBHOOK:
        return False
    try:
        data = json.dumps({"content": msg[:1900]}).encode("utf-8")
        req  = urllib.request.Request(DISCORD_WEBHOOK, data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False

send_discord_message = None
for p in ["/app/discord/discord_notify.py",
          os.path.abspath(os.path.join(Path(__file__).parent, "discord", "discord_notify.py"))]:
    if Path(p).is_file():
        try:
            spec = importlib.util.spec_from_file_location("discord_notify", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            send_discord_message = getattr(mod, "send_discord_message", None)
            break
        except Exception as e:
            print(f"[DEBUG] Failed to import discord_notify from {p}: {e}", flush=True)

def notify(msg: str):
    if send_discord_message:
        try:
            send_discord_message(msg); return
        except Exception:
            pass
    _discord_via_webhook(msg)

# --------- Logging ----------
def _now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

# --------- Signals ----------
def _handle_stop(signum, frame):
    global RUN
    log(f"Received signal {signum}. Stopping…")
    RUN = False

signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)

# --------- Subprocess helper ----------
def run_cmd(cmd, title=None, cwd=None, extra_env=None):
    if title:
        dlog(f"RUN {title}: {' '.join(cmd)} (cwd={cwd or os.getcwd()})")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        if DEBUG and out:
            dlog(f"{title or 'cmd'} STDOUT:\n{out}")
        if DEBUG and err:
            dlog(f"{title or 'cmd'} STDERR:\n{err}")
        return res.returncode, out, err
    except FileNotFoundError as e:
        log(f"[ERROR] {title or 'cmd'} not found: {e}")
        notify(f"❌ monitor_loop: {title or 'cmd'} not found.")
        return 127, "", str(e)
    except Exception as e:
        log(f"[ERROR] {title or 'cmd'} exception: {e}")
        notify(f"❌ monitor_loop: {title or 'cmd'} exception: {e}")
        return 1, "", str(e)

# --------- Étapes ----------
def step_quick_check():
    if not Path(QUICK_CHECK).is_file():
        dlog(f"QUICK_CHECK not found at {QUICK_CHECK}; skipping.")
        return True
    rc, _, _ = run_cmd(["python3", QUICK_CHECK], title="run_quick_check", cwd="/app")
    return rc == 0

def step_alerts():
    if not Path(MONITOR_REPAIR).is_file():
        log(f"[ERROR] monitor_repair not found at {MONITOR_REPAIR}")
        notify("❌ monitor_loop: monitor_repair.py introuvable.")
        return False
    extra_env = {"ALERT_STATE_FILE": ALERT_STATE_FILE}
    rc, _, _ = run_cmd(
        ["python3", MONITOR_REPAIR, "--alerts", "--alerts-from", MONITOR_LOG_FILE],
        title="alerts",
        cwd=str(Path(MONITOR_REPAIR).parent),
        extra_env=extra_env,
    )
    return rc == 0

def step_repair():
    if not Path(MONITOR_REPAIR).is_file():
        log(f"[ERROR] monitor_repair not found at {MONITOR_REPAIR}")
        notify("❌ monitor_loop: monitor_repair.py introuvable.")
        return False
    # 1) Vérification/réparation Deluge si marqué inactive
    rc, _, _ = run_cmd(["python3", MONITOR_REPAIR, "--deluge-verify"],
                       title="repair-deluge-verify",
                       cwd=str(Path(MONITOR_REPAIR).parent))
    if rc != 0:
        return False
    # 2) Mode AUTO: si Plex est 'offline' et cooldown OK, le test se déclenche
    rc2, _, _ = run_cmd(["python3", MONITOR_REPAIR],
                        title="repair-auto-plex",
                        cwd=str(Path(MONITOR_REPAIR).parent))
    return rc2 in (0,)

# --------- Main loop ----------
def main():
    # message de démarrage
    notify("🟢 monitor_loop: started.")
    log("monitor_loop started.")

    while RUN:
        cycle_start = time.time()
        try:
            # Étape 1: quick check (optionnel)
            dlog("Step: quick_check")
            step_quick_check()
            time.sleep(STEP_DELAY_SECONDS)

            # Étape 2: alerts
            dlog("Step: alerts")
            ok_alerts = step_alerts()
            if not ok_alerts:
                log("[WARN] alerts step returned non-zero.")

            time.sleep(STEP_DELAY_SECONDS)

            # Étape 3: repair (Deluge + auto Plex)
            dlog("Step: repair")
            ok_repair = step_repair()
            if not ok_repair:
                log("[WARN] repair step returned non-zero.")

        except Exception as e:
            log(f"[ERROR] loop exception: {e}")
            notify(f"❌ monitor_loop: exception {e}")

        elapsed = time.time() - cycle_start
        sleep_left = max(0, LOOP_INTERVAL_SECONDS - int(elapsed))
        dlog(f"Cycle finished in {int(elapsed)}s. Sleeping {sleep_left}s.")
        for _ in range(sleep_left):
            if not RUN:
                break
            time.sleep(1)

    log("monitor_loop stopped.")
    notify("🟡 monitor_loop: stopped.")

if __name__ == "__main__":
    main()
