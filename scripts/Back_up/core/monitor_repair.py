#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File name: monitor_repair.py
"""
Unified alerts + repair orchestrator (single-file edition).

Combines:
- alerts.py (anti-flap alerts reading /mnt/data/system_monitor_log.json → /mnt/data/alert_state.json)
- repair.py (Deluge verify/repair orchestration, Plex external test cadence + cooldown, Discord notify)
- plex_online.py (embedded) -- can also call external if present
- ip_adresse_up.py (embedded) -- can also call external if present (also detects ip_adress_up.py)

CLI (high level):
  --alerts [--alerts-from PATH]
  --deluge-verify
  --deluge-repair
  --plex-online [--force] [--plex-repair-mode {never,on-fail,always}] [--plex-discord]
  --deluge-ip-up [--ip-mode {never,on-fail,always}|--ip-always] [--ip-dry-run] [--deluge-ip-force]
  --all   # alerts → deluge verify → plex test (force cooldown bypass)

Environment (highlights):
  MONITOR_LOG_FILE, ALERT_STATE_FILE
  LOCAL_FAILS_FOR_ALERT, LOCAL_SUCCESSES_TO_CLEAR, EXTERNAL_FAILS_FOR_ALERT, EXTERNAL_SUCCESSES_TO_CLEAR
  PLEX_TEST_COOLDOWN, AUTO_PLEX_FORCE
  DELUGE_CONFIG_PATH (/app/config/deluge/core.conf), VPN_CONTAINER, DELUGE_CONTAINER
  CONTAINER (nginx-proxy), PLEX_CONTAINER, DOMAIN, CONF_PATH, LE_PATH, DUCKDNS_DOMAIN, DUCKDNS_TOKEN
  DISCORD_WEBHOOK (used by embedded scripts if --plex-discord or deluge-ip-up flow runs)

Notes:
- If external scripts exist, we’ll prefer them. Otherwise we run the embedded implementations below.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# =========================
# Robust .env loading
# =========================
def _simple_parse_env(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
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
    uniq, seen = [], set()
    for p in candidates:
        try: rp = p.resolve()
        except Exception: rp = p
        if rp not in seen:
            seen.add(rp); uniq.append(rp)
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

# =========================
# Constants & paths
# =========================
BASE_DIR = Path(__file__).resolve().parent

# Alert files/paths
LOG_FILE = os.environ.get("MONITOR_LOG_FILE", "/mnt/data/system_monitor_log.json")
ALERT_STATE_FILE = os.environ.get("ALERT_STATE_FILE", "/mnt/data/alert_state.json")

# Anti-flap thresholds (can be overridden via env)
LOCAL_FAILS_FOR_ALERT = int(os.getenv("LOCAL_FAILS_FOR_ALERT", "3"))
LOCAL_SUCCESSES_TO_CLEAR = int(os.getenv("LOCAL_SUCCESSES_TO_CLEAR", "2"))
EXTERNAL_FAILS_FOR_ALERT = int(os.getenv("EXTERNAL_FAILS_FOR_ALERT", "3"))
EXTERNAL_SUCCESSES_TO_CLEAR = int(os.getenv("EXTERNAL_SUCCESSES_TO_CLEAR", "2"))

# Repair config / cooldown
CONFIG_PATH = os.environ.get("DELUGE_CONFIG_PATH", os.environ.get("DELUGE_CORE_CONF", "/app/config/deluge/core.conf"))
PLEX_TEST_COOLDOWN = int(os.environ.get("PLEX_TEST_COOLDOWN", "300"))
AUTO_PLEX_FORCE = os.environ.get("AUTO_PLEX_FORCE", "0") == "1"

# =========================
# Path resolution helpers
# =========================
def _project_root_guess() -> Path | None:
    if os.environ.get("ROOT"):
        return Path(os.environ["ROOT"]).resolve()
    cur = BASE_DIR
    for _ in range(8):
        if (cur / "scripts").is_dir():
            return cur
        if cur.parent == cur: break
        cur = cur.parent
    cur = Path.cwd().resolve()
    for _ in range(8):
        if (cur / "scripts").is_dir():
            return cur
        if cur.parent == cur: break
        cur = cur.parent
    return None

def _first_existing(paths):
    for p in paths:
        if not p: continue
        pp = Path(p)
        if pp.is_file():
            return pp.resolve()
    return None

def resolve_plex_online_script() -> Path | None:
    root = _project_root_guess()
    candidates = [
        BASE_DIR / "plex_online.py",
        (root / "scripts/tool/plex_online.py") if root else None,
        Path("/app/tool/plex_online.py"),
        Path("/app/monitor/repair/plex_online.py"),
        Path("/app/repair/plex_online.py"),
    ]
    return _first_existing(candidates)

def resolve_deluge_ip_script() -> Path | None:
    root = _project_root_guess()
    candidates = [
        BASE_DIR / "ip_adresse_up.py",         # French spelling
        BASE_DIR / "ip_adress_up.py",          # earlier spelling
        (root / "scripts/core/repair/ip_adresse_up.py") if root else None,
        (root / "scripts/core/repair/ip_adress_up.py") if root else None,
        Path("/app/repair/ip_adresse_up.py"),
        Path("/app/repair/ip_adress_up.py"),
    ]
    return _first_existing(candidates)

# =========================
# Discord setup (shared simple sender)
# =========================
def _simple_discord_send(msg: str):
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not hook: return
    try:
        data = json.dumps({"content": msg[:1900]}).encode("utf-8")
        req = urllib.request.Request(hook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        pass

# =========================
# Alert state helpers
# =========================
def _default_alert_state():
    return {
        "plex_local":   {"status": "unknown", "failure_streak": 0, "success_streak": 0},
        "plex_external":{"status": "unknown", "failure_streak": 0, "success_streak": 0},
        "deluge_status":"unknown",
        "plex_external_status": "unknown",
        "plex_last_test_ts": 0,
    }

def load_alert_state():
    try:
        if os.path.exists(ALERT_STATE_FILE):
            with open(ALERT_STATE_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    base = _default_alert_state()
                    for k, v in base.items():
                        if isinstance(v, dict): data.setdefault(k, v)
                        else: data.setdefault(k, v)
                    if "plex_external_status" not in data:
                        data["plex_external_status"] = (data.get("plex_external", {}) or {}).get("status", "unknown")
                    return data
    except Exception:
        pass
    return _default_alert_state()

def save_alert_state(state):
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

# =========================
# JSON helpers (tolerant readers/writers)
# =========================
def read_last_entry_universal(path):
    """
    Supporte :
      - fichier = objet unique -> retourne l'objet
      - fichier = tableau d'objets -> retourne le dernier
      - fichier = NDJSON (1 objet JSON par ligne) -> retourne la dernière ligne valide
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
    except FileNotFoundError:
        return None
    if not txt:
        return None

    # 1) JSON "normal"
    try:
        obj = json.loads(txt)
        if isinstance(obj, list):
            return obj[-1] if obj else None
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2) NDJSON (dernière ligne non vide + valide)
    last = None
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        last = ln
    if last:
        try:
            return json.loads(last)
        except Exception:
            return None
    return None

# =========================
# Alerts: log reading + checks
# =========================
def read_latest_data(log_path: str | Path = LOG_FILE):
    data = read_last_entry_universal(log_path)
    if data is None:
        print(f"[ERROR] Unable to read data (empty or invalid): {log_path}")
    return data

def check_plex_local(data, state):
    plex = data.get("plex", {}) or {}
    local_access = bool(plex.get("local_access", False))
    connected = bool(plex.get("connected", False))
    is_up = local_access or connected
    node = state.setdefault("plex_local", {"status": "unknown", "failure_streak": 0, "success_streak": 0})
    prev_status = node.get("status", "unknown")
    if is_up:
        node["success_streak"] += 1; node["failure_streak"] = 0
        if prev_status != "online" and node["success_streak"] >= LOCAL_SUCCESSES_TO_CLEAR:
            node["status"] = "online"; print("[OK] Plex is accessible locally.")
            if prev_status == "offline": _simple_discord_send("[ALERT - END] Plex local access restored.")
    else:
        node["failure_streak"] += 1; node["success_streak"] = 0
        if prev_status != "offline" and node["failure_streak"] >= EXTERNAL_FAILS_FOR_ALERT:
            node["status"] = "offline"; print("[ALERT] Plex local access lost.")
            _simple_discord_send("[ALERT - initial] Plex local access lost (after consecutive failures).")
    state["plex_local"] = node

def check_plex_external(data, state):
    plex = data.get("plex", {}) or {}
    external_access = str(plex.get("external_access", "")).lower()
    external_detail = str(plex.get("external_detail", ""))
    is_up = (external_access == "yes")
    node = state.setdefault("plex_external", {"status": "unknown", "failure_streak": 0, "success_streak": 0})
    prev_status = node.get("status", "unknown")
    if is_up:
        node["success_streak"] += 1; node["failure_streak"] = 0
        if prev_status != "online" and node["success_streak"] >= EXTERNAL_SUCCESSES_TO_CLEAR:
            node["status"] = "online"; print("[OK] Plex is accessible externally.")
            if prev_status == "offline": _simple_discord_send("[ALERT - END] Plex is online from outside.")
    else:
        node["failure_streak"] += 1; node["success_streak"] = 0
        if prev_status != "offline" and node["failure_streak"] >= EXTERNAL_FAILS_FOR_ALERT:
            node["status"] = "offline"; print("[ALERT] Plex external access lost.")
            if "via_ip_ok" in external_detail:
                _simple_discord_send("[ALERT - initial] External DNS resolution appears broken (fallback IP works).")
            elif external_access == "error":
                _simple_discord_send(f"[ALERT] Plex external check error: {external_detail}")
            else:
                _simple_discord_send("[ALERT - initial] Plex appears offline from outside (after consecutive failures).")
    state["plex_external"] = node
    state["plex_external_status"] = node["status"]

def check_deluge(data, state):
    deluge = data.get("deluge", {}) or {}
    download_kbps = deluge.get("download_rate_kbps", 0.0)
    upload_kbps = deluge.get("upload_rate_kbps", 0.0)
    current_state = "inactive" if download_kbps == 0.0 and upload_kbps == 0.0 else "active"
    last_state = state.get("deluge_status")
    if current_state == "inactive" and last_state != "inactive":
        print("[ALERT] Deluge has become inactive.")
        _simple_discord_send("[ALERT - initial] Deluge appears inactive: no traffic detected.")
    elif current_state == "active" and last_state == "inactive":
        print("[OK] Deluge is active again.")
        _simple_discord_send("[ALERT - END] Deluge is active again.")
    state["deluge_status"] = current_state

def run_alerts_once(log_path: str | Path = LOG_FILE):
    print("[MONITOR] Alerts evaluation...")
    data = read_latest_data(log_path)
    if data is None:
        print("[WARN] No data to evaluate.")
        return 1
    state = load_alert_state()
    check_plex_external(data, state)
    check_plex_local(data, state)
    check_deluge(data, state)
    save_alert_state(state)
    return 0

# =========================
# Shared proc helpers
# =========================
def run(cmd, timeout=None):
    shell = isinstance(cmd, str)
    p = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout or None)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def run_and_send(cmd, title="Task", cwd: Path | None = None):
    print(f"[RUN] {title}: {' '.join(cmd)} (cwd={cwd or Path.cwd()})")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd.as_posix() if cwd else None)
    except FileNotFoundError as e:
        msg = f"[ERROR] {title} introuvable: {e}"
        print(msg); _simple_discord_send(msg); return 127
    output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    tail = output[-1800:] if output else "(no output)"
    status = "OK" if res.returncode == 0 else f"ERROR({res.returncode})"
    print(f"[{status}] {title}\n----- LOG (tail) -----\n{tail}\n----------------------")
    if res.returncode == 0:
        _simple_discord_send(f"[OK] {title} completed")
    else:
        _simple_discord_send(f"[ERROR] {title} failed (exit={res.returncode}).")
    return res.returncode

# =========================
# DELUGE verify/repair (legacy helpers)
# =========================
def get_vpn_internal_ip():
    print("[INFO] Récupération IP interne VPN (tun0) depuis conteneur 'vpn'…")
    result = subprocess.run(["docker", "exec", os.environ.get("VPN_CONTAINER","vpn"), "ip", "addr", "show", "tun0"],
                            capture_output=True, text=True)
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
    ips = {"listen_interface": listen.group(1) if listen else None,
           "outgoing_interface": outgoing.group(1) if outgoing else None}
    print(f"[INFO] Interfaces Deluge: {ips}")
    return ips

# -------- Deluge RPC helpers (read/write config) --------
def _deluge_rpc_client(
    host="localhost", port=58846,
    user="localclient",
    password="e0db9d7d51b2c62b7987031174607aa822f94bc9",
    try_connect=True,
):
    try:
        from deluge_client import DelugeRPCClient
        c = DelugeRPCClient(host, port, user, password, False)
        if try_connect:
            c.connect()
        return c
    except Exception as e:
        print(f"[WARN] Deluge RPC client unavailable: {e}")
        return None

def _deluge_get_config_rpc():
    c = _deluge_rpc_client()
    if not c:
        return None
    try:
        cfg = c.call("core.get_config")
        def b2s(x): return x.decode("utf-8","ignore") if isinstance(x,(bytes,bytearray)) else x
        cfg = { b2s(k): b2s(v) for k,v in cfg.items() }
        return {
            "listen_interface":   cfg.get("listen_interface"),
            "outgoing_interface": cfg.get("outgoing_interface"),
        }
    except Exception as e:
        print(f"[WARN] RPC get_config failed: {e}")
        return None

def _deluge_set_interfaces_rpc(vpn_ip: str) -> bool:
    c = _deluge_rpc_client()
    if not c:
        return False
    try:
        c.call("core.set_config", {
            "listen_interface": vpn_ip,
            "outgoing_interface": vpn_ip,
        })
        print(f"[ACTION] RPC set_config applied (listen/outgoing = {vpn_ip})")
        return True
    except Exception as e:
        print(f"[FAIL] RPC set_config failed: {e}")
        return False

def verify_interface_consistency():
    """
    Compare Deluge listen/outgoing avec l'IP VPN (tun0).
    Priorité à la lecture RPC (read-only). Fallback fichier si RPC KO.
    Retour: (consistent: bool, vpn_ip: str, extras: dict)
    """
    try:
        vpn_ip = get_vpn_internal_ip()
    except Exception as e:
        print(f"[WARN] No VPN IP found on tun0 ({e}); assuming consistent to avoid false repair.")
        return True, "", {}

    # 1) Lecture via RPC (préférée)
    conf = _deluge_get_config_rpc()
    if conf:
        listen = conf.get("listen_interface")
        outgoing = conf.get("outgoing_interface")
        consistent = (listen == vpn_ip) and (outgoing == vpn_ip)
        print(f"[INFO] Interfaces Deluge (RPC) listen={listen!r}, outgoing={outgoing!r} vs VPN={vpn_ip} -> {consistent}")
        return consistent, vpn_ip, {"listen": listen, "outgoing": outgoing}

    # 2) Fallback fichier (lecture seule, tolérante)
    print("[WARN] RPC not available, fallback to file read.")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        raw = re.sub(r"//.*?$", "", raw, flags=re.M)
        raw = re.sub(r"#.*?$",  "", raw, flags=re.M)
        if "{" in raw and "}" in raw:
            raw = raw[ raw.find("{"): raw.rfind("}")+1 ]
        raw = re.sub(r",(\s*[}\]])", r"\1", raw)
        conf = json.loads(raw)
    except Exception as e:
        print(f"[WARN] Unable to read Deluge config (RPC + file both failed): {e}")
        return True, vpn_ip, {}

    listen = conf.get("listen_interface")
    outgoing = conf.get("outgoing_interface")
    consistent = (listen == vpn_ip) and (outgoing == vpn_ip)
    print(f"[INFO] Interfaces Deluge (file) listen={listen!r}, outgoing={outgoing!r} vs VPN={vpn_ip} -> {consistent}")
    return consistent, vpn_ip, {"listen": listen, "outgoing": outgoing}

# =========================
# EMBEDDED: ip_adresse_up.py
# =========================
def embedded_ip_adresse_up(mode_cli=None, always=False, repair=False, force=False, dry_run=False):
    VPN_CONTAINER      = os.environ.get("VPN_CONTAINER", "vpn")
    DELUGE_CONTAINER   = os.environ.get("DELUGE_CONTAINER", "deluge")
    CONFIG_PATH_LOCAL  = os.environ.get("DELUGE_CONFIG_PATH", CONFIG_PATH)
    MODE_AUTO_DEFAULT  = os.environ.get("MODE_AUTO", "never").strip().lower()
    def _discord_send(msg): _simple_discord_send(msg)

    def _run(cmd):
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

    def _get_vpn_ip():
        rc, out, err = _run(["docker", "exec", VPN_CONTAINER, "ip", "addr", "show", "dev", "tun0"])
        if rc != 0:
            msg = f"Cannot read tun0 in container '{VPN_CONTAINER}': {err or out}"
            print(f"[FAIL] {msg}"); _discord_send(f"❌ *ip_adresse_up*: {msg}")
            return None
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None

    def _load_core_conf(path):
        import json as _json, re as _re
        if not os.path.isfile(path):
            msg = f"Missing Deluge config: {path}"
            print(f"[FAIL] {msg}"); _discord_send(f"❌ *ip_adresse_up*: {msg}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception as e1:
            try:
                raw = Path(path).read_text(encoding="utf-8")
                raw = _re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
                raw = _re.sub(r"//.*?$", "", raw, flags=re.M)
                raw = _re.sub(r"#.*?$", "", raw, flags=re.M)
                if "{" in raw and "}" in raw:
                    raw = raw[raw.find("{"): raw.rfind("}")+1]
                raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
                return _json.loads(raw)
            except Exception as e2:
                msg = f"Could not read JSON: {e2} (initial error: {e1})"
                print(f"[FAIL] {msg}"); _discord_send(f"❌ *ip_adresse_up*: {msg}")
                return None

    def _atomic_write_json(path, data):
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2); f.write("\n")
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

    def _restart_deluge():
        print(f"[ACTION] Restarting '{DELUGE_CONTAINER}'…"); _discord_send(f"🔄 *ip_adresse_up*: redémarrage de `{DELUGE_CONTAINER}`…")
        rc, out, err = _run(["docker", "restart", DELUGE_CONTAINER])
        if rc == 0:
            print("[OK] Deluge restarted."); _discord_send("✅ *ip_adresse_up*: Deluge redémarré."); return True
        msg = f"Deluge restart failed: {err or out}"
        print(f"[FAIL] {msg}"); _discord_send(f"❌ *ip_adresse_up*: {msg}"); return False

    _discord_send("🔍 *ip_adresse_up*: démarrage du check.")
    # mode resolution (CLI > env)
    if always: mode = "always"
    elif mode_cli: mode = mode_cli
    else: mode = MODE_AUTO_DEFAULT
    mode = mode.strip().lower() if mode else "never"
    if mode not in {"never","on-fail","always"}: mode = "never"
    print(f"[INFO] MODE (effective):  {mode}")
    _discord_send(f"⚙️ *ip_adresse_up*: mode **{mode}**{' + DRY-RUN' if dry_run else ''}.")

    vpn_ip = _get_vpn_ip()
    if not vpn_ip:
        print("[FAIL] No VPN IP detected on tun0.")
        _discord_send("🔴 *ip_adresse_up*: aucune IP sur `tun0` (VPN down ?).")
        print("[HINT] Check VPN container is up and tun0 exists.")
        return 1

    print(f"[OK] VPN internal IP: {vpn_ip}")
    _discord_send(f"🟢 *ip_adresse_up*: IP VPN détectée **{vpn_ip}**.")

    # --- RPC-first path (read/write via Deluge, pas de fichier) ---
    conf_rpc = _deluge_get_config_rpc()
    if conf_rpc is not None:
        listen_old = conf_rpc.get("listen_interface")
        outgoing_old = conf_rpc.get("outgoing_interface")
        need_change  = (listen_old != vpn_ip) or (outgoing_old != vpn_ip)

        print(f"[INFO] (RPC) listen_interface:  {listen_old!r}")
        print(f"[INFO] (RPC) outgoing_interface:{outgoing_old!r}")
        print(f"[INFO] MODE (effective):  {mode}")

        # Décision
        apply_change = False
        if dry_run:
            plan = f"(RPC) Would set listen_interface/outgoing_interface to {vpn_ip}"
            print(f"[PLAN] {plan}")
            _discord_send(f"📝 *ip_adresse_up*: DRY-RUN — {plan}")
            if force:
                if not _restart_deluge(): return 1
            return 0
        else:
            if mode == "always": apply_change = True
            elif mode == "on-fail": apply_change = need_change
            elif mode == "never": apply_change = (repair and need_change)

        if not apply_change:
            if not need_change:
                print("[OK] (RPC) Config already pinned to VPN IP. No changes required.")
                _discord_send("✅ *ip_adresse_up*: (RPC) config déjà alignée.")
            else:
                plan = f"(RPC) Would set listen/outgoing to {vpn_ip} (use --repair or --mode)."
                print(f"[PLAN] {plan}")
                _discord_send(f"📝 *ip_adresse_up*: DRY-RUN — {plan}")
            if force:
                if not _restart_deluge(): return 1
            return 0

        # Application via RPC
        if _deluge_set_interfaces_rpc(vpn_ip):
            _discord_send(f"🛠️ *ip_adresse_up*: (RPC) set listen/outgoing -> {vpn_ip}")
            if not _restart_deluge(): return 1
            return 0
        else:
            print("[WARN] RPC write failed; fallback to file path.")
    # --- end RPC-first path ---

    # Fallback fichier (écriture tolérante)
    conf = _load_core_conf(CONFIG_PATH_LOCAL)
    if conf is None: return 1

    listen_old   = conf.get("listen_interface")
    outgoing_old = conf.get("outgoing_interface")
    need_change  = (listen_old != vpn_ip) or (outgoing_old != vpn_ip)

    print(f"[INFO] core.conf at: {CONFIG_PATH_LOCAL}")
    print(f"[INFO] listen_interface:  {listen_old!r}")
    print(f"[INFO] outgoing_interface:{outgoing_old!r}")

    # decision
    apply_change = False
    if dry_run:
        apply_change = False
    else:
        if mode == "always": apply_change = True
        elif mode == "on-fail": apply_change = need_change
        elif mode == "never": apply_change = (repair and need_change)

    if not apply_change:
        if not need_change:
            print("[OK] Config already pinned to VPN IP. No changes required.")
            _discord_send("✅ *ip_adresse_up*: core.conf déjà aligné sur l’IP VPN.")
        else:
            plan = f"Would set listen_interface/outgoing_interface to {vpn_ip} (use --repair or --mode)."
            print(f"[PLAN] {plan}")
            _discord_send(f"📝 *ip_adresse_up*: DRY-RUN — {plan}")
        if force:
            if not _restart_deluge(): return 1
        return 0

    # apply (fichier)
    conf["listen_interface"]   = vpn_ip
    conf["outgoing_interface"] = vpn_ip
    try:
        _atomic_write_json(CONFIG_PATH_LOCAL, conf)
        msg = f"core.conf updated to VPN IP {vpn_ip}."
        print(f"[ACTION] {msg}")
        _discord_send(f"🛠️ *ip_adresse_up*: {msg}")
    except Exception as e:
        err = f"Could not write core.conf: {e}"
        print(f"[FAIL] {err}")
        _discord_send(f"❌ *ip_adresse_up*: {err}")
        return 1

    if not _restart_deluge(): return 1
    return 0

def launch_repair_deluge_ip():
    script = resolve_deluge_ip_script()
    if script:
        return run_and_send(["python3", script.as_posix()], "Deluge IP repair", cwd=script.parent)
    # fallback to embedded
    return embedded_ip_adresse_up(mode_cli=None, always=False, repair=True, force=False, dry_run=False)

def handle_deluge_verification():
    state = load_alert_state()
    if state.get("deluge_status") != "inactive":
        print("[INFO] Deluge non marqué 'inactive' → skip vérification."); return
    _simple_discord_send("[ALERT] Deluge appears inactive: validating…")
    consistent, vpn_ip, _ = verify_interface_consistency()
    if not consistent:
        _simple_discord_send("[CONFIRMED] IP mismatch: repairing Deluge.")
        rc = launch_repair_deluge_ip()
        if rc == 0:
            _simple_discord_send(f"[DONE] Deluge IP updated to {vpn_ip}")
    else:
        print("[INFO] Deluge IPs cohérentes, pas de réparation nécessaire.")

# =========================
# EMBEDDED: plex_online.py
# =========================
def embedded_plex_online(repair_mode="never", discord=False):
    # Settings (compatible with your script)
    CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")
    PLEX_CONTAINER = os.environ.get("PLEX_CONTAINER", "plex-server")
    DOMAIN_RAW = os.environ.get("DOMAIN", "plex-robert.duckdns.org")
    DOMAIN = re.sub(r"^https?://", "", DOMAIN_RAW).split("/")[0]
    CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")
    LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")
    UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
    UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")
    CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))
    SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"
    WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))
    DUCKDNS_DOMAIN = os.environ.get("DUCKDNS_DOMAIN", "").strip()
    DUCKDNS_TOKEN = os.environ.get("DUCKDNS_TOKEN", "").strip()
    if not DUCKDNS_DOMAIN and DOMAIN.endswith(".duckdns.org"):
        DUCKDNS_DOMAIN = DOMAIN.split(".duckdns.org", 1)[0]
    SEND_DISCORD = bool(discord)

    def _discord_send(msg: str):
        if SEND_DISCORD:
            _simple_discord_send(msg)

    def require(binname): return shutil.which(binname) is not None
    def docker_container_running(name):
        rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
        return rc == 0 and any(line.strip() == name for line in out.splitlines())
    def docker_exec(args, timeout=None): return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)
    def _have_cmd(cmd: str) -> bool: return shutil.which(cmd) is not None

    def _dig_a(domain: str, server: str, timeout=1.5, tries=1):
        try:
            rc, out, _ = run(["dig","+short",f"+time={int(timeout)}",f"+tries={int(tries)}","A",domain,f"@{server}"], timeout=timeout+0.5)
            if rc == 0 and out.strip():
                ips = [l.strip() for l in out.splitlines() if re.match(r"^\d+\.\d+\.\d+\.\d+$", l.strip())]
                return ips
        except Exception:
            pass
        return []

    def resolve_a_multi(domain: str, resolvers=None, timeout=1.5, tries=1):
        if resolvers is None: resolvers = ["1.1.1.1","8.8.8.8","9.9.9.9"]
        answers, logs = set(), []
        if _have_cmd("dig"):
            for s in resolvers:
                ips = _dig_a(domain, s, timeout=timeout, tries=tries)
                logs.append(f"[DNS] @{s} -> {ips if ips else '∅'}")
                answers.update(ips)
        if not answers:
            try:
                ai = socket.getaddrinfo(domain, 0, family=socket.AF_INET, type=socket.SOCK_STREAM)
                ips = sorted({t[4][0] for t in ai})
                logs.append(f"[DNS] system -> {ips if ips else '∅'}")
                answers.update(ips)
            except Exception as e:
                logs.append(f"[DNS] system -> error: {e}")
        return answers, logs

    def get_public_ip():
        for endpoint in (["curl","-sS","-4","https://ifconfig.me"],
                         ["curl","-sS","-4","https://api.ipify.org"],
                         ["curl","-sS","-4","https://ipv4.icanhazip.com"]):
            rc, out, _ = run(endpoint)
            ip = (out or "").strip()
            if rc == 0 and ip.count(".") == 3:
                return ip
        return ""

    def parse_notafter_to_days(exp_line):
        exp_norm = re.sub(r"\s{2,}", " ", exp_line)
        exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return int((exp_dt - now).total_seconds() // 86400), exp_dt

    # Tests
    results = {}
    def header(m): print(f"\n=== {m} ===")
    def ok(m): print(f"[ OK ] {m}")
    def warn(m): print(f"[WARN] {m}")
    def fail(m): print(f"[FAIL] {m}")
    def info(m): print(f"[INFO] {m}")

    header("Preflight")
    ok_all = True
    for b in ("docker","curl"):
        if not require(b):
            fail(f"Missing required host binary: {b}"); ok_all = False
    if docker_container_running(CONTAINER): ok(f"Container '{CONTAINER}' is running.")
    else: fail(f"Container '{CONTAINER}' is NOT running."); ok_all = False
    if PLEX_CONTAINER:
        if docker_container_running(PLEX_CONTAINER): ok(f"Plex container '{PLEX_CONTAINER}' is running.")
        else: warn(f"Plex container '{PLEX_CONTAINER}' not running.")
    url = f"http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/identity"
    rc, out, _ = run(["curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}",url])
    if rc == 0 and out.strip() == "200": ok(f"Plex fallback upstream replied 200 on /identity ({UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}).")
    else: warn(f"Fallback Plex upstream test failed at {url} (code {out or 'n/a'}).")
    if not ok_all:
        results["_reason_PREFLIGHT"] = "preflight checks failed (missing binaries or containers down)"
    results["PREFLIGHT"] = ok_all

    header("Check nginx config presence")
    rc, _, err = docker_exec(["ls","-l","/etc/nginx/conf.d"])
    if rc != 0:
        fail(f"Cannot list conf.d: {err}"); results["CONF_PRESENT"]=False; results["_reason_CONF_PRESENT"]="cannot list /etc/nginx/conf.d)"
    else:
        rc2,_,_ = docker_exec(["sh","-lc",f"test -f {shlex.quote(CONF_PATH)}"])
        if rc2 == 0:
            ok(f"Found {CONF_PATH} in container."); results["CONF_PRESENT"]=True
        else:
            fail(f"Missing {CONF_PATH} in container."); results["CONF_PRESENT"]=False; results["_reason_CONF_PRESENT"]=f"missing {CONF_PATH} in container"

    header("Check nginx config syntax (nginx -t)")
    rc, out, err = docker_exec(["nginx","-t"])
    if rc == 0:
        ok("nginx -t: syntax OK"); results["NGINX_TEST"]=True
    else:
        fail(f"nginx -t error:\n{out}\n{err}"); results["NGINX_TEST"]=False; results["_reason_NGINX_TEST"]="nginx -t error (see logs)"

    header("Extract upstream from plex.conf")
    rc, out, _ = docker_exec(["sh","-lc", f"awk '/proxy_pass[[:space:]]+http/{{print $2}}' {shlex.quote(CONF_PATH)} | head -n1 | tr -d ';'"])
    url = out.strip() if rc == 0 else ""
    if not url:
        warn(f"No proxy_pass found. Using fallback {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}")
        host,port = (UPSTREAM_FALLBACK_HOST, UPSTREAM_FALLBACK_PORT)
    else:
        no_scheme = re.sub(r"^https?://", "", url); no_path = no_scheme.split("/",1)[0]
        if ":" in no_path: host, port = no_path.split(":",1)
        else: host, port = no_path, "80"
        ok(f"Detected upstream target: {host}:{port}")
    results["UPSTREAM_FROM_CONF"]=True

    header("Test Plex upstream (/identity) from inside container")
    rc, out, _ = docker_exec(["curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}", f"http://{host}:{port}/identity"])
    if rc == 0 and out.strip()=="200":
        ok("Plex upstream replied 200 on /identity."); results["PLEX_UPSTREAM"]=True
    else:
        fail(f"Plex upstream test failed (HTTP {out or 'n/a'})."); results["PLEX_UPSTREAM"]=False; results["_reason_PLEX_UPSTREAM"]=f"HTTP {out or 'n/a'} from upstream {host}:{port}/identity"

    header("DuckDNS IP vs current public IP")
    ips, dns_logs = resolve_a_multi(DOMAIN)
    for line in dns_logs: info(line)
    if not ips:
        fail("No A records returned by any resolver."); results["DNS_MATCH"]=False; results["_reason_DNS_MATCH"]="no A records from public resolvers"
    else:
        info(f"Resolved {DOMAIN} -> {sorted(ips)}"); results["duckdns_ips"]=sorted(ips)
        pub_ip = results.get("_pub_ip") or get_public_ip()
        if pub_ip:
            ok(f"Current public IP: {pub_ip}"); results["_pub_ip"]=pub_ip
            match = pub_ip in ips
            if match: ok(f"DuckDNS resolves to current public IP: {pub_ip}")
            else: fail(f"DuckDNS does not match current public IP ({pub_ip}); resolved={sorted(ips)}"); results["_reason_DNS_MATCH"]=f"resolved={sorted(ips)}, public={pub_ip}"
            results["DNS_MATCH"]=match; results["_duck_ip"]=sorted(ips)[0] if ips else ""
        else:
            fail("Unable to fetch current public IP."); results["DNS_MATCH"]=False; results["_reason_DNS_MATCH"]="unable to fetch current public IP"

    header("Check certificate files and expiration")
    rc1,_,_ = docker_exec(["sh","-lc", f"test -f {shlex.quote(LE_PATH)}/fullchain.pem"])
    rc2,_,_ = docker_exec(["sh","-lc", f"test -f {shlex.quote(LE_PATH)}/privkey.pem"])
    if rc1==0 and rc2==0: ok(f"Found cert files under {LE_PATH} (fullchain.pem & privkey.pem).")
    else:
        fail(f"Cert files not found at {LE_PATH}."); results["CERT_EXPIRY"]=False; results["_reason_CERT_EXPIRY"]=f"cert files missing at {LE_PATH}"
    if results.get("CERT_EXPIRY", True) is not False:
        exp_line = ""
        has_in = docker_exec(["sh","-lc","command -v openssl >/dev/null 2>&1"])[0] == 0
        if has_in:
            rc,out,_ = docker_exec(["sh","-lc", f"openssl x509 -enddate -noout -in {shlex.quote(LE_PATH)}/fullchain.pem | cut -d= -f2"])
            if rc==0 and out.strip(): exp_line = out.strip()
        if not exp_line and shutil.which("openssl"):
            rc,pem,err = docker_exec(["sh","-lc", f"cat {shlex.quote(LE_PATH)}/fullchain.pem"])
            if rc==0 and pem:
                p = subprocess.run(["openssl","x509","-enddate","-noout"], input=pem, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if p.returncode==0 and p.stdout.strip(): exp_line = p.stdout.strip().split("=",1)[-1].strip()
        if not exp_line and shutil.which("openssl"):
            rc,out,_ = run(f"echo | openssl s_client -connect {shlex.quote(DOMAIN)}:443 -servername {shlex.quote(DOMAIN)} 2>/dev/null | openssl x509 -noout -enddate")
            if rc==0 and out.strip().startswith("notAfter="): exp_line = out.strip().split("=",1)[-1].strip()
        if not exp_line:
            fail("Could not determine certificate expiration."); results["CERT_EXPIRY"]=False; results["_reason_CERT_EXPIRY"]="cannot determine certificate expiration"
        else:
            try:
                days_left, exp_dt = parse_notafter_to_days(exp_line)
                if days_left < 0:
                    fail(f"Certificate EXPIRED {abs(days_left)} days ago (expires: {exp_dt})."); results["CERT_EXPIRY"]=False; results["_reason_CERT_EXPIRY"]=f"certificate expired (notAfter={exp_dt})"
                elif days_left < WARN_DAYS:
                    warn(f"Certificate will expire in {days_left} days (expires: {exp_dt})."); results["CERT_EXPIRY"]=True
                else:
                    ok(f"Certificate valid for {days_left} more days (expires: {exp_dt})."); results["CERT_EXPIRY"]=True
                results["_cert_days_left"]=days_left
            except Exception as e:
                fail(f"Failed to parse cert date '{exp_line}': {e}"); results["CERT_EXPIRY"]=False; results["_reason_CERT_EXPIRY"]="cannot parse certificate expiration"

    if not SIMULATE_EXTERNAL:
        results["HTTPS_EXTERNAL"]=True
    else:
        header("Simulated external HTTPS (curl --resolve to public IP)")
        pub_ip = results.get("_pub_ip","")
        if not pub_ip:
            fail("No public IP available; skipping external simulation."); results["HTTPS_EXTERNAL"]=False; results["_reason_HTTPS_EXTERNAL"]="no public IP available for --resolve test"
        else:
            rc,out,_ = run(["curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}","--resolve", f"{DOMAIN}:443:{pub_ip}", f"https://{DOMAIN}/"])
            code = out.strip() if rc == 0 else ""
            if code in {"200","301","302","401","403"}:
                ok(f"HTTPS answered with HTTP {code} at {DOMAIN} (forced to {pub_ip})."); results["HTTPS_EXTERNAL"]=True
            else:
                fail(f"No HTTPS answer (code '{code or 'timeout'}')."); results["HTTPS_EXTERNAL"]=False; results["_reason_HTTPS_EXTERNAL"]=f"https://{DOMAIN} no valid HTTP answer via --resolve ({code or 'timeout'})"

    # results aggregation
    def _collect_failures(results):
        TESTS = ["PREFLIGHT","CONF_PRESENT","NGINX_TEST","UPSTREAM_FROM_CONF","PLEX_UPSTREAM","DNS_MATCH","CERT_EXPIRY","HTTPS_EXTERNAL"]
        failures = []
        for k in TESTS:
            if results.get(k) is False:
                failures.append(k)
        return failures

    def _results_success(): _discord_send("[Results] Test passed: Plex online.")
    def _results_failed_list(failing_keys, results):
        LABELS = {
            "PREFLIGHT":"Preflight","CONF_PRESENT":"Nginx config presence","NGINX_TEST":"Nginx syntax test",
            "UPSTREAM_FROM_CONF":"Upstream extraction","PLEX_UPSTREAM":"Plex upstream /identity",
            "DNS_MATCH":"DNS matches public IP","CERT_EXPIRY":"TLS certificate validity","HTTPS_EXTERNAL":"HTTPS external access"
        }
        lines = ["[Results] Failed tests:"]
        for k in failing_keys:
            label = LABELS.get(k, k)
            reason = results.get(f"_reason_{k}")
            lines.append(f"- {label}: {reason}" if reason else f"- {label}")
        _discord_send("\n".join(lines))

    def repair_dns(pub_ip: str) -> bool:
        if not DUCKDNS_DOMAIN or not DUCKDNS_TOKEN:
            fail("DNS repair failed: missing DUCKDNS_DOMAIN or DUCKDNS_TOKEN")
            return False
        try:
            url = f"https://www.duckdns.org/update?domains={DUCKDNS_DOMAIN}&token={DUCKDNS_TOKEN}&ip={pub_ip}"
            with urllib.request.urlopen(url, timeout=8) as r:
                body = r.read().decode().strip().upper()
                if "OK" in body:
                    ok(f"[REPAIR][DNS_MATCH] Updated DuckDNS {DUCKDNS_DOMAIN}.duckdns.org -> {pub_ip}")
                    return True
                else:
                    fail(f"[REPAIR][DNS_MATCH] DuckDNS update failed: {body}")
                    return False
        except Exception as e:
            fail(f"[REPAIR][DNS_MATCH] Exception: {e}")
            return False

    def _announce_availability_for_all(failed_tests, results, mode: str):
        dns_reason = results.get("_reason_DNS_MATCH", "DNS does not match public IP")
        if "DNS_MATCH" in failed_tests or mode == "always":
            _discord_send(f"[Repair] Repair available: Update DuckDNS IP — reason: {dns_reason}")
        for t in failed_tests:
            if t != "DNS_MATCH":
                _discord_send(f"[Repair] Repair not available: {t} — no automated fix")

    def _run_repairs(mode: str, failed_tests, results):
        _announce_availability_for_all(failed_tests, results, mode)
        if mode == "never": return
        targets = failed_tests if mode == "on-fail" else (failed_tests or ["DNS_MATCH"])
        for t in targets:
            if t == "DNS_MATCH":
                pub = results.get("_pub_ip","") or get_public_ip()
                if not pub:
                    _discord_send("[Repair] Fail: Update DuckDNS IP — error: public IP unavailable"); continue
                _discord_send("[Repair] Launch: Update DuckDNS IP")
                repaired = repair_dns(pub)
                if repaired: _discord_send("[Repair] Success: Update DuckDNS IP")
                else: _discord_send("[Repair] Fail: Update DuckDNS IP — provider rejected or network error")
            else:
                _discord_send(f"[Repair] Repair not available: {t} — no automated fix")

    failing = _collect_failures(results)
    if not failing and results.get("HTTPS_EXTERNAL", True):
        _results_success()
    else:
        _results_failed_list(failing, results)
    _run_repairs(repair_mode, failing, results)
    return 0 if not failing else 2

def resolve_plex_online_cmd():
    script = resolve_plex_online_script()
    if not script: return None, None
    return ["python3", script.as_posix()], script.parent

def should_run_plex_online_test(force=False):
    if force: print("[DECISION] Test Plex forcé → True"); return True
    state = load_alert_state()
    nested = (state.get("plex_external") or {}).get("status")
    flat = state.get("plex_external_status")
    status = nested or flat
    if nested and flat and nested != flat:
        state["plex_external_status"] = nested; save_alert_state(state); print(f"[FIX] Harmonized plex_external_status -> {nested}")
    now = time.time()
    last = state.get("plex_last_test_ts", 0)
    print(f"[DECISION] plex_external_status={status}, now={now}, last={last}, cooldown={PLEX_TEST_COOLDOWN}")
    if status != "offline":
        print("[DECISION] Plex n'est pas 'offline' → skip test"); return False
    if (now - last) < PLEX_TEST_COOLDOWN:
        print("[DECISION] Cooldown non expiré → skip test"); return False
    print("[DECISION] Conditions réunies → lancer test Plex"); return True

def launch_plex_online_test(repair_mode: str | None = None, discord: bool = False):
    # Prefer external if present
    cmd_base, cwd = resolve_plex_online_cmd()
    if cmd_base:
        attempts = []
        if repair_mode in ("never","on-fail","always"):
            attempts.append(cmd_base + ["--repair", repair_mode] + (["--discord"] if discord else []))
        attempts.append(cmd_base[:] + (["--discord"] if discord else []))
        last_rc = 2; last_tail = ""
        for i, attempt in enumerate(attempts, 1):
            print(f"[RUN] Plex online test (try {i}/{len(attempts)}): {' '.join(attempt)} (cwd={cwd or Path.cwd()})")
            res = subprocess.run(attempt, capture_output=True, text=True, cwd=cwd.as_posix() if cwd else None)
            out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
            tail = out[-1800:] if out else "(no output)"
            print(f"[TRY {i}] exit={res.returncode}\n----- LOG (tail) -----\n{tail}\n----------------------")
            last_rc, last_tail = res.returncode, tail
            if res.returncode == 0: break
            if res.returncode != 2: break
        # DuckDNS propagation auto-retry (only meaningful for external tool’s 2 exit)
        if last_rc == 2 and ("Updated DuckDNS" in (last_tail or "")):
            for j in range(6):
                time.sleep(10)
                res = subprocess.run(cmd_base[:] + (["--discord"] if discord else []),
                                     capture_output=True, text=True, cwd=cwd.as_posix() if cwd else None)
                out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                tail = out[-1800:] if out else "(no output)"
                print(f"[RECHECK {j+1}/6] exit={res.returncode}\n----- LOG (tail) -----\n{tail}\n----------------------")
                last_rc, last_tail = res.returncode, tail
                if res.returncode == 0: break
        # mirror timestamp
        state = load_alert_state(); state["plex_last_test_ts"] = time.time(); save_alert_state(state)
        return last_rc
    # Fallback to embedded implementation
    rc = embedded_plex_online(repair_mode=repair_mode or "never", discord=discord)
    state = load_alert_state(); state["plex_last_test_ts"] = time.time(); save_alert_state(state)
    return rc

# =========================
# CLI
# =========================
def main():
    print("[DEBUG] monitor_repair.py is running")
    parser = argparse.ArgumentParser(description="Unified health/alerts/repair orchestrator (single-file)")
    # Alerts
    parser.add_argument("--alerts", action="store_true", help="Run alert checks once using the latest entry from the monitor log")
    parser.add_argument("--alerts-from", dest="alerts_from", default=LOG_FILE, help=f"Path to the monitor log file (default: {LOG_FILE})")
    # Original repair flags
    parser.add_argument("--deluge-verify", action="store_true", help="Vérifier/réparer Deluge si nécessaire (only if alert_state marks inactive)")
    parser.add_argument("--deluge-repair", action="store_true", help="Forcer la réparation IP de Deluge")
    parser.add_argument("--plex-online", action="store_true", help="Lancer le test Plex online")
    parser.add_argument("--force", action="store_true", help="Ignorer les conditions et cooldowns (utilisé avec --plex-online)")
    parser.add_argument("--all", action="store_true", help="Lancer alerts + tous les tests et réparations disponibles")
    # ip_adresse_up (Deluge)
    parser.add_argument("--deluge-ip-up", action="store_true", help="Met à jour core.conf avec l'IP VPN et redémarre Deluge si nécessaire")
    parser.add_argument("--deluge-ip-force", action="store_true", help="Force le redémarrage de Deluge même sans changement")
    parser.add_argument("--ip-mode", choices=["never","on-fail","always"], help="Passe le mode à ip_adresse_up (override MODE_AUTO)")
    parser.add_argument("--ip-always", action="store_true", help="Alias de --ip-mode always")
    parser.add_argument("--ip-dry-run", action="store_true", help="N'écrit pas; affiche les actions prévues pour ip_adresse_up")
    # plex_online relays
    parser.add_argument("--plex-repair-mode", choices=["never","on-fail","always"], help="Passe le mode à plex_online (override MODE_AUTO)")
    parser.add_argument("--plex-discord", action="store_true", help="Active les notifications Discord dans plex_online")
    args = parser.parse_args()

    # Mode batch "all": alerts → deluge verify → plex
    if args.all:
        run_alerts_once(args.alerts_from)
        handle_deluge_verification()
        env_mode = os.getenv("MODE_AUTO", "").strip().lower()
        env_discord = os.getenv("PLEX_ONLINE_DISCORD", "0") == "1"
        if should_run_plex_online_test(force=True):
            launch_plex_online_test(
                repair_mode=(args.plex_repair_mode or (env_mode if env_mode in ("never","on-fail","always") else None)),
                discord=(args.plex_discord or env_discord),
            )
        return

    # Selective
    if args.alerts:
        run_alerts_once(args.alerts_from)

    if args.deluge_ip_up or args.deluge_ip_force:
        # prefer external if present; else run embedded
        script = resolve_deluge_ip_script()
        if script:
            cmd = ["python3", script.as_posix()]
            if args.ip_always: cmd.append("--always")
            elif args.ip_mode: cmd += ["--mode", args.ip_mode]
            # default compatibility: add --repair if mode is None/never (on-fail apply)
            if args.ip_mode in (None, "never"): cmd.append("--repair")
            if args.deluge_ip_force: cmd.append("--force")
            if args.ip_dry_run: cmd.append("--dry-run")
            run_and_send(cmd, "Deluge IP update", cwd=script.parent)
        else:
            embedded_ip_adresse_up(
                mode_cli=("always" if args.ip_always else args.ip_mode),
                always=False,
                repair=(args.ip_mode in (None,"never")),  # match prior behavior
                force=args.deluge_ip_force,
                dry_run=args.ip_dry_run,
            )

    if args.deluge_verify:
        handle_deluge_verification()

    if args.deluge_repair:
        launch_repair_deluge_ip()

    if args.plex_online:
        env_mode = os.getenv("MODE_AUTO", "").strip().lower()
        env_discord = os.getenv("PLEX_ONLINE_DISCORD", "0") == "1"
        if should_run_plex_online_test(force=args.force):
            launch_plex_online_test(
                repair_mode=(args.plex_repair_mode or (env_mode if env_mode in ("never","on-fail","always") else None)),
                discord=(args.plex_discord or env_discord),
            )
        else:
            print("[INFO] Plex online test skipped (status not offline ou cooldown).")

    # AUTO when nothing explicit: trigger Plex test if marked offline
    ran_anything = any([
        args.all, args.alerts, args.deluge_verify, args.deluge_repair,
        args.plex_online, args.deluge_ip_up, args.deluge_ip_force
    ])
    if not ran_anything:
        state = load_alert_state()
        if state.get("plex_external_status") == "offline":
            print("[AUTO] Plex est marqué 'offline' → lancement du test Plex")
            if should_run_plex_online_test(force=AUTO_PLEX_FORCE):
                env_mode = os.getenv("MODE_AUTO", "").strip().lower()
                env_discord = os.getenv("PLEX_ONLINE_DISCORD", "0") == "1"
                launch_plex_online_test(
                    repair_mode=(env_mode if env_mode in ("never","on-fail","always") else None),
                    discord=env_discord,
                )
            else:
                print("[AUTO] Conditions non réunies (cooldown ou état) → test non lancé")

if __name__ == "__main__":
    main()
