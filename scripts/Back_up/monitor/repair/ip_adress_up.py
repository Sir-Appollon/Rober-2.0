#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ip_adresse_up.py
- Lit l'IP VPN (tun0) dans le conteneur VPN.
- Compare avec les valeurs Deluge dans core.conf (listen_interface / outgoing_interface).
- Répare selon le MODE_AUTO (env) ou le mode CLI.
- Envoie des notifications Discord si DISCORD_WEBHOOK est défini.

MODES (env MODE_AUTO ou --mode)
  never   : pas de modification (dry-run), sauf si --repair
  on-fail : répare seulement si la conf diffère de l'IP VPN
  always  : répare (applique) à chaque exécution

CLI (priorité > env)
  --mode {never,on-fail,always}  # surclasse MODE_AUTO
  --always                       # équivalent à --mode always
  --repair                       # applique en mode on-fail, même si MODE_AUTO=never
  --force                        # redémarre Deluge même sans modif
  --dry-run                      # force dry-run (n’écrit pas), utile pour tester

ENV attendus
  VPN_CONTAINER=vpn
  DELUGE_CONTAINER=deluge
  DELUGE_CONFIG_PATH=/app/config/deluge/core.conf
  MODE_AUTO=never|on-fail|always
  DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
import urllib.request
import urllib.error

VPN_CONTAINER      = os.environ.get("VPN_CONTAINER", "vpn")
DELUGE_CONTAINER   = os.environ.get("DELUGE_CONTAINER", "deluge")
CONFIG_PATH        = os.environ.get("DELUGE_CONFIG_PATH", "/app/config/deluge/core.conf")
MODE_AUTO_DEFAULT  = os.environ.get("MODE_AUTO", "never").strip().lower()  # env par défaut
DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "").strip()

# --------------- Discord helper ----------------
def _discord_send(content: str):
    """Poste un message simple sur Discord si DISCORD_WEBHOOK est défini. No-op sinon."""
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": content[:1900]}).encode("utf-8")
        req = urllib.request.Request(DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as _:
            pass
    except Exception:
        # ne pas casser le script si Discord est injoignable
        pass

# ----------------- utils proc -----------------
def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def get_vpn_internal_ip():
    rc, out, err = run(["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "dev", "tun0"])
    if rc != 0:
        msg = f"Cannot read tun0 in container '{VPN_CONTAINER}': {err or out}"
        print(f"[FAIL] {msg}")
        _discord_send(f"❌ *ip_adresse_up*: {msg}")
        return None
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None

def load_core_conf(path):
    if not os.path.isfile(path):
        msg = f"Missing Deluge config: {path}"
        print(f"[FAIL] {msg}")
        _discord_send(f"❌ *ip_adresse_up*: {msg}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        msg = f"Could not read JSON: {e}"
        print(f"[FAIL] {msg}")
        _discord_send(f"❌ *ip_adresse_up*: {msg}")
        return None

def atomic_write_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak-{ts}"
    try:
        if os.path.exists(path):
            os.replace(path, bak)
            print(f"[INFO] Backup saved: {bak}")
            _discord_send(f"🗄️ *ip_adresse_up*: backup créé `{bak}`")
    except Exception as e:
        print(f"[WARN] Could not create backup: {e}")
        _discord_send(f"⚠️ *ip_adresse_up*: backup non créé ({e})")
    os.replace(tmp, path)

def restart_deluge():
    print(f"[ACTION] Restarting '{DELUGE_CONTAINER}'…")
    _discord_send(f"🔄 *ip_adresse_up*: redémarrage de `{DELUGE_CONTAINER}`…")
    rc, out, err = run(["docker", "restart", DELUGE_CONTAINER])
    if rc == 0:
        print("[OK] Deluge restarted.")
        _discord_send("✅ *ip_adresse_up*: Deluge redémarré.")
        return True
    msg = f"Deluge restart failed: {err or out}"
    print(f"[FAIL] {msg}")
    _discord_send(f"❌ *ip_adresse_up*: {msg}")
    return False

# ----------------- main -----------------
def main():
    _discord_send("🔍 *ip_adresse_up*: démarrage du check.")
    ap = argparse.ArgumentParser(description="Update Deluge core.conf with VPN tun0 IP.")
    ap.add_argument("--mode", choices=["never","on-fail","always"],
                    help="override MODE_AUTO env")
    ap.add_argument("--always", action="store_true",
                    help="shortcut for --mode always")
    ap.add_argument("--repair", action="store_true",
                    help="apply changes if needed (on-fail) even if MODE_AUTO=never")
    ap.add_argument("--force", action="store_true",
                    help="restart Deluge even if no change was needed")
    ap.add_argument("--dry-run", action="store_true",
                    help="do not write; just show actions")
    args = ap.parse_args()

    # Résolution du mode effectif (priorité CLI)
    if args.always:
        mode = "always"
    elif args.mode:
        mode = args.mode
    else:
        mode = MODE_AUTO_DEFAULT  # env
    mode = mode.strip().lower()
    if mode not in {"never","on-fail","always"}:
        mode = "never"
    print(f"[INFO] MODE (effective):  {mode}")
    _discord_send(f"⚙️ *ip_adresse_up*: mode **{mode}**{' + DRY-RUN' if args.dry_run else ''}.")

    vpn_ip = get_vpn_internal_ip()
    if not vpn_ip:
        print("[FAIL] No VPN IP detected on tun0.")
        _discord_send("🔴 *ip_adresse_up*: aucune IP sur `tun0` (VPN down ?).")
        print("[HINT] Check VPN container is up and tun0 exists.")
        sys.exit(1)

    print(f"[OK] VPN internal IP: {vpn_ip}")
    _discord_send(f"🟢 *ip_adresse_up*: IP VPN détectée **{vpn_ip}**.")

    conf = load_core_conf(CONFIG_PATH)
    if conf is None:
        sys.exit(1)

    listen_old   = conf.get("listen_interface")
    outgoing_old = conf.get("outgoing_interface")
    need_change  = (listen_old != vpn_ip) or (outgoing_old != vpn_ip)

    print(f"[INFO] core.conf at: {CONFIG_PATH}")
    print(f"[INFO] listen_interface:  {listen_old!r}")
    print(f"[INFO] outgoing_interface:{outgoing_old!r}")

    # Décision d'application
    apply_change = False
    if args.dry_run:
        apply_change = False
    else:
        if mode == "always":
            apply_change = True
        elif mode == "on-fail":
            apply_change = need_change
        elif mode == "never":
            # autoriser l’application si l’utilisateur a explicitement demandé --repair (on-fail)
            apply_change = args.repair and need_change

    if not apply_change:
        # Pas d'application → logs + option de restart forcé
        if not need_change:
            print("[OK] Config already pinned to VPN IP. No changes required.")
            _discord_send("✅ *ip_adresse_up*: core.conf déjà aligné sur l’IP VPN.")
        else:
            plan = f"Would set listen_interface/outgoing_interface to {vpn_ip} (use --repair or --mode)."
            print(f"[PLAN] {plan}")
            _discord_send(f"📝 *ip_adresse_up*: DRY-RUN — {plan}")
        if args.force:
            if not restart_deluge():
                sys.exit(1)
        sys.exit(0)

    # Application : mise à jour + restart
    conf["listen_interface"]   = vpn_ip
    conf["outgoing_interface"] = vpn_ip
    try:
        atomic_write_json(CONFIG_PATH, conf)
        msg = f"core.conf updated to VPN IP {vpn_ip}."
        print(f"[ACTION] {msg}")
        _discord_send(f"🛠️ *ip_adresse_up*: {msg}")
    except Exception as e:
        err = f"Could not write core.conf: {e}"
        print(f"[FAIL] {err}")
        _discord_send(f"❌ *ip_adresse_up*: {err}")
        sys.exit(1)

    if not restart_deluge():
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
