#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plex_online_lite.py
Health check minimal pour Plex (fallback upstream) + test/réparation DuckDNS.
+ Notifications Discord via DISCORD_WEBHOOK (optionnel)

ENV (utilisés)
  UPSTREAM_FALLBACK_HOST=192.168.3.39
  UPSTREAM_FALLBACK_PORT=32400
  CURL_TIMEOUT=10
  MODE_AUTO=never            # never|on-fail|always (modifiable via --always)

  # Pour le test + réparation DuckDNS :
  DUCKDNS_SUBDOMAIN=plex-robert    # SANS .duckdns.org (ex: "plex-robert")
  DUCKDNS_TOKEN=xxxxxxxxxxxxxxxx   # Token DuckDNS

  # Discord (optionnel)
  DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

USAGE
  python3 plex_online_lite.py
  python3 plex_online_lite.py --json
  python3 plex_online_lite.py --repair                 # répare les tests en échec (dont DuckDNS)
  python3 plex_online_lite.py --repair --force         # lance toutes les réparations
  python3 plex_online_lite.py --always                 # équivaut à MODE_AUTO=always
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
import urllib.error

# ================== DOCUMENTATION DES TESTS / ERREURS ==================
#
# TESTS EFFECTUÉS :
# 1) PREFLIGHT
#    - Vérifie la présence de `curl` sur l'hôte.
#    ERREURS :
#      [FAIL] Missing required host binary: curl
#    RÉPARATION :
#      - Installer curl (apt/yum/apk selon l'OS).
#
# 2) PLEX_UPSTREAM
#    - Vérifie la réponse HTTP 200 de Plex local :
#        http://<UPSTREAM_FALLBACK_HOST>:<UPSTREAM_FALLBACK_PORT>/identity
#    ERREURS :
#      [FAIL] Plex upstream test failed (HTTP n/a ou code != 200).
#    RÉPARATION :
#      - S'assurer que Plex est démarré et écoute sur le port.
#      - Tester depuis l'hôte :
#          curl http://HOST:PORT/identity
#      - Vérifier pare-feu/réseau/variables d'env (HOST/PORT).
#
# 3) DNS_MATCH (DuckDNS)
#    - Compare l'IP publique actuelle avec l'enregistrement A de
#      <DUCKDNS_SUBDOMAIN>.duckdns.org
#    ERREURS :
#      [WARN/FAIL] DuckDNS does not match current public IP.
#      [WARN] No A records returned (DNS).
#      [WARN] Unable to fetch current public IP.
#    RÉPARATION :
#      - Si DUCKDNS_SUBDOMAIN et DUCKDNS_TOKEN sont définis :
#          Met à jour DuckDNS via l'API officielle (ip auto-détectée côté DuckDNS).
#        Sinon, affiche la commande à exécuter et quoi configurer.
#
# MODES DE RÉPARATION :
#   --repair          → répare uniquement les tests en échec.
#   --repair --force  → force toutes les réparations (même si les tests passent).
#   --always          → équivaut à MODE_AUTO=always (répare tout à chaque run).
#
# =======================================================================

UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")
CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))
MODE_AUTO = os.environ.get("MODE_AUTO", "never")  # never|on-fail|always

# DuckDNS
DUCKDNS_SUBDOMAIN = os.environ.get("DUCKDNS_SUBDOMAIN", "").strip()  # ex: "plex-robert"
DUCKDNS_TOKEN = os.environ.get("DUCKDNS_TOKEN", "").strip()

# Discord
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()

TESTS = ["PREFLIGHT", "PLEX_UPSTREAM", "DNS_MATCH"]

def _discord_send(content: str):
    """Envoie un message simple sur Discord si DISCORD_WEBHOOK est défini. No-op sinon."""
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": content[:1900]}).encode("utf-8")
        req = urllib.request.Request(DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as _:
            pass
    except Exception:
        # Evite de casser le script si Discord est injoignable
        pass

def color(tag, msg):
    codes = {"INFO":"\033[1;34m","OK":"\033[1;32m","WARN":"\033[1;33m","FAIL":"\033[1;31m","HDR":"\033[1;36m","END":"\033[0m"}
    return f"{codes.get(tag,'')}{msg}{codes['END']}"

def info(m):   print(color("INFO","[INFO] "), m)
def ok(m):     print(color("OK","[ OK ] "), m)
def warn(m):   print(color("WARN","[WARN] "), m); _discord_send(f"⚠️ {m}")
def fail(m):   print(color("FAIL","[FAIL] "), m); _discord_send(f"❌ {m}")
def header(m): print(color("HDR", f"\n=== {m} ==="))

def run(cmd, timeout=None):
    shell = isinstance(cmd, str)
    p = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout or None)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def require(binname):
    return shutil.which(binname) is not None

# ------------------ HELPERS RÉSEAU ------------------ #
def get_public_ip():
    """
    Retourne l'IP publique IPv4 en interrogeant des services publics (fallback).
    """
    endpoints = [
        ["curl","-sS","-4","https://ifconfig.me"],
        ["curl","-sS","-4","https://api.ipify.org"],
        ["curl","-sS","-4","https://ipv4.icanhazip.com"],
    ]
    for ep in endpoints:
        rc, out, _ = run(ep, timeout=CURL_TIMEOUT+2)
        ip = (out or "").strip()
        if rc == 0 and ip.count(".") == 3:
            return ip
    return ""

def resolve_a(domain: str):
    """
    Résout des A-records IPv4 via le résolveur système (pas de dépendance à 'dig').
    Retourne une liste unique triée d'IPs (str).
    """
    try:
        ai = socket.getaddrinfo(domain, 0, family=socket.AF_INET, type=socket.SOCK_STREAM)
        ips = sorted({t[4][0] for t in ai})
        return ips
    except Exception as e:
        warn(f"DNS system resolve error for {domain}: {e}")
        return []

# ------------------ TESTS ------------------ #
def test_preflight(results):
    header("Preflight")
    _discord_send("🔍 **Plex Lite**: démarrage du health check.")
    ok_all = True
    if not require("curl"):
        fail("Missing required host binary: curl")
        ok_all = False
    else:
        ok("curl is available.")
    results["PREFLIGHT"] = ok_all
    return ok_all

def test_upstream(results, host, port):
    header("Test Plex upstream (/identity) from host")
    rc, out, _ = run([
        "curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}",
        f"http://{host}:{port}/identity"
    ], timeout=CURL_TIMEOUT+2)
    if rc == 0 and out.strip() == "200":
        ok(f"Plex upstream replied 200 on /identity at {host}:{port}.")
        results["PLEX_UPSTREAM"] = True
        return True
    fail(f"Plex upstream test failed at {host}:{port} (HTTP {out or 'n/a'}).")
    results["PLEX_UPSTREAM"] = False
    return False

def test_dns_duckdns(results):
    header("DuckDNS vs Public IP")
    if not DUCKDNS_SUBDOMAIN:
        warn("DUCKDNS_SUBDOMAIN not set; skipping DNS_MATCH test.")
        results["DNS_MATCH"] = False
        return False

    fqdn = f"{DUCKDNS_SUBDOMAIN}.duckdns.org"
    ips = resolve_a(fqdn)
    if not ips:
        warn(f"No A records for {fqdn}.")
        results["DNS_MATCH"] = False
        return False
    info(f"Resolved {fqdn} -> {ips}")
    results["_duck_ips"] = ips

    pub_ip = get_public_ip()
    if not pub_ip:
        warn("Unable to fetch current public IP.")
        results["DNS_MATCH"] = False
        return False
    ok(f"Current public IP: {pub_ip}")
    results["_pub_ip"] = pub_ip

    match = pub_ip in ips
    if match:
        ok(f"DuckDNS matches current public IP: {pub_ip}")
    else:
        warn(f"DuckDNS does not match current public IP ({pub_ip}); resolved={ips}")
    results["DNS_MATCH"] = match
    return match

# ------------------ REPAIRS ------------------ #
def repair_preflight():
    header("Repair: PREFLIGHT")
    if not require("curl"):
        warn("curl not installed. Install it with apt/yum/apk depending on your OS.")
    else:
        ok("curl already installed; nothing to repair.")

def repair_upstream():
    header("Repair: PLEX_UPSTREAM")
    warn("Automatic repair not possible for Plex upstream.")
    info("Checklist:")
    info(f" - Verify Plex is running on {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}")
    info(f" - Try: curl http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/identity")
    info(" - Check firewall/NAT/route/container status")

def repair_dns_match():
    header("Repair: DNS_MATCH (DuckDNS)")
    if not DUCKDNS_SUBDOMAIN or not DUCKDNS_TOKEN:
        warn("DUCKDNS_SUBDOMAIN and/or DUCKDNS_TOKEN not set; cannot auto-update DuckDNS.")
        info("Set env then re-run with --repair. Example:")
        info("  DUCKDNS_SUBDOMAIN=my-sub DUCKDNS_TOKEN=xxxx python3 plex_online_lite.py --repair")
        return
    url = f"https://www.duckdns.org/update?domains={DUCKDNS_SUBDOMAIN}&token={DUCKDNS_TOKEN}&ip="
    _discord_send(f"🛠️ Tentative de mise à jour DuckDNS pour **{DUCKDNS_SUBDOMAIN}.duckdns.org** …")
    rc, out, err = run(["curl","-sS",url], timeout=CURL_TIMEOUT+4)
    status = (out or "").strip().upper()
    if rc == 0 and status == "OK":
        ok("DuckDNS updated successfully (server-side auto-detect).")
        _discord_send("✅ DuckDNS mis à jour avec succès (auto IP).")
    else:
        fail(f"DuckDNS update failed: rc={rc}, resp='{out}', err='{err}'")
        _discord_send(f"❌ DuckDNS update FAILED (rc={rc}, resp='{out}')")

ACTIONS = {
    "PREFLIGHT": repair_preflight,
    "PLEX_UPSTREAM": repair_upstream,
    "DNS_MATCH": repair_dns_match,
}

# ------------------ CLI ------------------ #
def _parse_args():
    p = argparse.ArgumentParser(description="Minimal Plex health check (lite) + DuckDNS repair + Discord")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument("--repair", action="store_true", help="attempt repairs if tests fail")
    p.add_argument("--force", action="store_true", help="force all repairs regardless of test results")
    p.add_argument("--always", action="store_true", help="set MODE_AUTO=always")
    return p.parse_args()

def _compute_failures(results):
    failures = [k for k in TESTS if results.get(k) is False]
    overall_ok = (len(failures) == 0)
    return failures, overall_ok

# ------------------ MAIN ------------------ #
def main():
    global MODE_AUTO
    args = _parse_args()
    if args.always:
        MODE_AUTO = "always"

    results = {}
    test_preflight(results)
    test_upstream(results, UPSTREAM_FALLBACK_HOST, UPSTREAM_FALLBACK_PORT)
    test_dns_duckdns(results)

    failing, overall_ok = _compute_failures(results)

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    if overall_ok:
        ok("All critical checks passed.")
        _discord_send("🟢 **Plex Lite**: tous les checks sont OK.")
    else:
        fail("One or more checks failed.")
        _discord_send(f"🔴 **Plex Lite**: échec de {', '.join(failing)}")

    # Mode réparation
    if args.repair or MODE_AUTO in {"on-fail", "always"}:
        if args.force or MODE_AUTO == "always":
            to_repair = TESTS[:]  # toutes
            _discord_send("🛠️ Mode réparation: **FORCE/ALWAYS** → toutes les réparations lancées.")
        else:
            to_repair = [t for t in failing]  # seulement celles en échec
            if to_repair:
                _discord_send(f"🛠️ Mode réparation: tests en échec → {', '.join(to_repair)}")
        for t in to_repair:
            fn = ACTIONS.get(t)
            if fn:
                fn()

    sys.exit(0 if overall_ok else 2)

if __name__ == "__main__":
    main()
