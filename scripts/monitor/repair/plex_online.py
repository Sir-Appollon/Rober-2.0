#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plex_online.py
Health checks for Plex + Nginx (Docker). DNS repair is implemented inline.
Other repairs are not implemented yet (logs + Discord notice only).

USAGE
  python3 plex_online.py
  python3 plex_online.py --repair on-fail
  python3 plex_online.py --repair always
  python3 plex_online.py --repair never
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
import urllib.request
from datetime import datetime, timezone

# --- Load .env early (must be before any os.environ reads) ---
ENV_PATH_USED = None
try:
    from dotenv import load_dotenv

    for _p in ("../../../.env", "/app/.env"):
        _abs = os.path.abspath(os.path.join(os.path.dirname(__file__), _p))
        if os.path.isfile(_abs):
            load_dotenv(_abs, override=True)  # <-- IMPORTANT
            ENV_PATH_USED = _abs
            break
except Exception:
    pass


# =========================== SETTINGS =========================== #
CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")
PLEX_CONTAINER = os.environ.get("PLEX_CONTAINER", "plex-server")

# Normalise DOMAIN (tolère https:// et /path)
DOMAIN_RAW = os.environ.get("DOMAIN", "plex-robert.duckdns.org")
DOMAIN = re.sub(r"^https?://", "", DOMAIN_RAW).split("/")[0]

CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")

UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")

CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))
SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"
WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))

# DNS repair env
DUCKDNS_DOMAIN = os.environ.get("DUCKDNS_DOMAIN", "").strip()
DUCKDNS_TOKEN = os.environ.get("DUCKDNS_TOKEN", "").strip()

# Auto‑déduction du sous‑domaine DuckDNS si absent (ex: 'plex-robert' depuis 'plex-robert.duckdns.org')
if not DUCKDNS_DOMAIN and DOMAIN.endswith(".duckdns.org"):
    DUCKDNS_DOMAIN = DOMAIN.split(".duckdns.org", 1)[0]


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return "(empty)"
    return s[:keep] + "…" if len(s) > keep else "…"


print(f"[INFO] .env used: {ENV_PATH_USED or '(none)'}")
print(f"[INFO] DOMAIN={DOMAIN}")
print(f"[INFO] DUCKDNS_DOMAIN={DUCKDNS_DOMAIN or '(auto-deduction failed)'}")
print(f"[INFO] DUCKDNS_TOKEN={_mask(DUCKDNS_TOKEN)}")


# Optionnel: webhook Discord
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()


# --- Sanity logs (token masqué) ---
def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return "(empty)"
    return s[:keep] + "…" if len(s) > keep else "…"


print(f"[INFO] DOMAIN={DOMAIN}")
print(f"[INFO] DUCKDNS_DOMAIN={DUCKDNS_DOMAIN or '(auto-deduction failed)'}")
print(f"[INFO] DUCKDNS_TOKEN={_mask(DUCKDNS_TOKEN)}")
if DISCORD_WEBHOOK:
    print("[INFO] DISCORD_WEBHOOK set")


# Liste ordonnée des tests
TESTS = [
    "PREFLIGHT",
    "CONF_PRESENT",
    "NGINX_TEST",
    "UPSTREAM_FROM_CONF",
    "PLEX_UPSTREAM",
    "DNS_MATCH",
    "CERT_EXPIRY",
    "HTTPS_EXTERNAL",
]


# ======================== UI / LOG HELPERS ====================== #
def _discord_send(msg: str):
    """Envoie un message au webhook Discord (silence si non configuré)."""
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg[:1900]}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass  # ne jamais faire échouer le script pour Discord


def _color(tag, msg):
    codes = {
        "INFO": "\033[1;34m",
        "OK": "\033[1;32m",
        "WARN": "\033[1;33m",
        "FAIL": "\033[1;31m",
        "HDR": "\033[1;36m",
        "END": "\033[0m",
    }
    return f"{codes.get(tag,'')}{msg}{codes['END']}"


def info(m):
    print(_color("INFO", "[INFO] "), m)


def ok(m):
    print(_color("OK", "[ OK ] "), m)


def warn(m):
    print(_color("WARN", "[WARN] "), m)
    _discord_send(f"⚠️ {m}")


def fail(m):
    print(_color("FAIL", "[FAIL] "), m)
    _discord_send(f"❌ {m}")


def header(m):
    print(_color("HDR", f"\n=== {m} ==="))


# ========================= PROC HELPERS ========================= #
def run(cmd, timeout=None):
    """Run a command; returns (rc, stdout, stderr)."""
    shell = isinstance(cmd, str)
    p = subprocess.run(
        cmd,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout or None,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def require(binname):
    return shutil.which(binname) is not None


def docker_exec(args, timeout=None):
    """docker exec into the nginx container."""
    return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)


def docker_container_running(name):
    rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
    return rc == 0 and any(line.strip() == name for line in out.splitlines())


# ==================== NET / DNS / CERT HELPERS ================== #
def _have_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _dig_a(domain: str, server: str, timeout=1.5, tries=1):
    """Resolve A records via dig."""
    try:
        rc, out, _ = run(
            [
                "dig",
                "+short",
                f"+time={int(timeout)}",
                f"+tries={int(tries)}",
                "A",
                domain,
                f"@{server}",
            ],
            timeout=timeout + 0.5,
        )
        if rc == 0 and out.strip():
            ips = [
                l.strip()
                for l in out.splitlines()
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", l.strip())
            ]
            return ips
    except Exception:
        pass
    return []


def resolve_a_multi(domain: str, resolvers=None, timeout=1.5, tries=1):
    """
    Résout les A-records IPv4 via plusieurs résolveurs publics (+fallback système).
    Retourne (answers_set, details_log)
    """
    if resolvers is None:
        resolvers = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]

    answers = set()
    logs = []

    if _have_cmd("dig"):
        for s in resolvers:
            ips = _dig_a(domain, s, timeout=timeout, tries=tries)
            logs.append(f"[DNS] @{s} -> {ips if ips else '∅'}")
            answers.update(ips)

    if not answers:
        # Fallback système
        try:
            ai = socket.getaddrinfo(
                domain, 0, family=socket.AF_INET, type=socket.SOCK_STREAM
            )
            ips = sorted({t[4][0] for t in ai})
            logs.append(f"[DNS] system -> {ips if ips else '∅'}")
            answers.update(ips)
        except Exception as e:
            logs.append(f"[DNS] system -> error: {e}")

    return answers, logs


def get_public_ip():
    """Get current public IPv4 with fallbacks."""
    for endpoint in (
        ["curl", "-sS", "-4", "https://ifconfig.me"],
        ["curl", "-sS", "-4", "https://api.ipify.org"],
        ["curl", "-sS", "-4", "https://ipv4.icanhazip.com"],
    ):
        rc, out, _ = run(endpoint)
        ip = (out or "").strip()
        if rc == 0 and ip.count(".") == 3:
            return ip
    return ""


def parse_notafter_to_days(exp_line):
    """Parse 'Jun  1 12:34:56 2025 GMT' -> (days_left, dt)."""
    exp_norm = re.sub(r"\s{2,}", " ", exp_line)
    exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z").replace(
        tzinfo=timezone.utc
    )
    now = datetime.now(timezone.utc)
    return int((exp_dt - now).total_seconds() // 86400), exp_dt


# ========================= REPAIRS ============================== #
def repair_dns(pub_ip: str) -> bool:
    """
    Met à jour DuckDNS pour pointer vers pub_ip.
    DUCKDNS_DOMAIN: sans .duckdns.org (ex: 'plex-robert')
    DUCKDNS_TOKEN: token DuckDNS
    """
    if not DUCKDNS_DOMAIN or not DUCKDNS_TOKEN:
        msg = "DNS repair failed: missing DUCKDNS_DOMAIN or DUCKDNS_TOKEN"
        fail(msg)
        return False
    try:
        url = f"https://www.duckdns.org/update?domains={DUCKDNS_DOMAIN}&token={DUCKDNS_TOKEN}&ip={pub_ip}"
        with urllib.request.urlopen(url, timeout=8) as r:
            body = r.read().decode().strip().upper()
            if "OK" in body:
                ok(
                    f"[REPAIR][DNS_MATCH] Updated DuckDNS {DUCKDNS_DOMAIN}.duckdns.org -> {pub_ip}"
                )
                _discord_send(
                    f"✅ DNS repaired: {DUCKDNS_DOMAIN}.duckdns.org now points to {pub_ip}"
                )
                return True
            else:
                msg = f"[REPAIR][DNS_MATCH] DuckDNS update failed: {body}"
                fail(msg)
                return False
    except Exception as e:
        fail(f"[REPAIR][DNS_MATCH] Exception: {e}")
        return False


def repair_generic(test_key: str):
    """Message pro pour réparations non implémentées."""
    msg = f"Repair not possible for {test_key} (not implemented yet)."
    info(msg)
    _discord_send(f"⚠️ {msg}")


# ============================ TESTS ============================= #
def test_preflight(results):
    header("Preflight")
    _discord_send("🔍 **plex_online**: starting health checks.")
    ok_all = True

    for b in ("docker", "curl"):
        if not require(b):
            fail(f"Missing required host binary: {b}")
            ok_all = False

    if docker_container_running(CONTAINER):
        ok(f"Container '{CONTAINER}' is running.")
    else:
        fail(f"Container '{CONTAINER}' is NOT running.")
        ok_all = False

    if PLEX_CONTAINER:
        if docker_container_running(PLEX_CONTAINER):
            ok(f"Plex container '{PLEX_CONTAINER}' is running.")
        else:
            warn(f"Plex container '{PLEX_CONTAINER}' not running.")

    # Quick upstream probe to your fallback (local Plex)
    url = f"http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/identity"
    rc, out, _ = run(
        [
            "curl",
            "-sS",
            "-m",
            str(CURL_TIMEOUT),
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            url,
        ]
    )
    if rc == 0 and out.strip() == "200":
        ok(
            f"Plex fallback upstream replied 200 on /identity ({UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT})."
        )
    else:
        warn(f"Fallback Plex upstream test failed at {url} (code {out or 'n/a'}).")

    results["PREFLIGHT"] = ok_all
    return ok_all


def test_conf_present(results):
    header("Check nginx config presence")
    rc, _, err = docker_exec(["ls", "-l", "/etc/nginx/conf.d"])
    if rc != 0:
        fail(f"Cannot list conf.d: {err}")
        results["CONF_PRESENT"] = False
        return False

    rc, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(CONF_PATH)}"])
    if rc == 0:
        ok(f"Found {CONF_PATH} in container.")
        results["CONF_PRESENT"] = True
        return True

    fail(f"Missing {CONF_PATH} in container.")
    results["CONF_PRESENT"] = False
    return False


def test_nginx_t(results):
    header("Check nginx config syntax (nginx -t)")
    rc, out, err = docker_exec(["nginx", "-t"])
    if rc == 0:
        ok("nginx -t: syntax OK")
        results["NGINX_TEST"] = True
        return True
    fail(f"nginx -t error:\n{out}\n{err}")
    results["NGINX_TEST"] = False
    return False


def extract_upstream():
    header("Extract upstream from plex.conf")
    rc, out, _ = docker_exec(
        [
            "sh",
            "-lc",
            f"awk '/proxy_pass[[:space:]]+http/{{print $2}}' {shlex.quote(CONF_PATH)} | head -n1 | tr -d ';'",
        ]
    )
    url = out.strip() if rc == 0 else ""
    if not url:
        warn(
            f"No proxy_pass found. Using fallback {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}"
        )
        return (UPSTREAM_FALLBACK_HOST, UPSTREAM_FALLBACK_PORT)

    no_scheme = re.sub(r"^https?://", "", url)
    no_path = no_scheme.split("/", 1)[0]
    if ":" in no_path:
        host, port = no_path.split(":", 1)
    else:
        host, port = no_path, "80"
    ok(f"Detected upstream target: {host}:{port}")
    return (host, port)


def test_upstream(results, host, port):
    header("Test Plex upstream (/identity) from inside container")
    rc, out, _ = docker_exec(
        [
            "curl",
            "-sS",
            "-m",
            str(CURL_TIMEOUT),
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            f"http://{host}:{port}/identity",
        ]
    )
    if rc == 0 and out.strip() == "200":
        ok("Plex upstream replied 200 on /identity.")
        results["PLEX_UPSTREAM"] = True
        return True
    fail(f"Plex upstream test failed (HTTP {out or 'n/a'}).")
    results["PLEX_UPSTREAM"] = False
    return False


def test_dns_match(results):
    header("DuckDNS IP vs current public IP")
    ips, dns_logs = resolve_a_multi(DOMAIN)
    for line in dns_logs:
        info(line)

    if not ips:
        fail("No A records returned by any resolver.")
        results["DNS_MATCH"] = False
        return False

    info(f"Resolved {DOMAIN} -> {sorted(ips)}")
    results["duckdns_ips"] = sorted(ips)

    pub_ip = results.get("_pub_ip") or get_public_ip()
    if pub_ip:
        ok(f"Current public IP: {pub_ip}")
        results["_pub_ip"] = pub_ip
    else:
        fail("Unable to fetch current public IP.")
        results["DNS_MATCH"] = False
        return False

    match = pub_ip in ips
    if match:
        ok(f"DuckDNS resolves to current public IP: {pub_ip}")
    else:
        fail(
            f"DuckDNS does not match current public IP ({pub_ip}); resolved={sorted(ips)}"
        )

    results["DNS_MATCH"] = match
    results["_duck_ip"] = sorted(ips)[0] if ips else ""
    return match


def test_cert_expiry(results):
    header("Check certificate files and expiration")
    rc1, _, _ = docker_exec(
        ["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/fullchain.pem"]
    )
    rc2, _, _ = docker_exec(
        ["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/privkey.pem"]
    )
    if rc1 == 0 and rc2 == 0:
        ok(f"Found cert files under {LE_PATH} (fullchain.pem & privkey.pem).")
    else:
        fail(f"Cert files not found at {LE_PATH}.")
        results["CERT_EXPIRY"] = False
        return False

    exp_line = ""
    has_in = docker_exec(["sh", "-lc", "command -v openssl >/dev/null 2>&1"])[0] == 0
    if has_in:
        rc, out, _ = docker_exec(
            [
                "sh",
                "-lc",
                f"openssl x509 -enddate -noout -in {shlex.quote(LE_PATH)}/fullchain.pem | cut -d= -f2",
            ]
        )
        if rc == 0 and out.strip():
            exp_line = out.strip()

    if not exp_line and shutil.which("openssl"):
        rc, pem, _ = docker_exec(
            ["sh", "-lc", f"cat {shlex.quote(LE_PATH)}/fullchain.pem"]
        )
        if rc == 0 and pem:
            p = subprocess.run(
                ["openssl", "x509", "-enddate", "-noout"],
                input=pem,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if p.returncode == 0 and p.stdout.strip():
                exp_line = p.stdout.strip().split("=", 1)[-1].strip()

    if not exp_line and shutil.which("openssl"):
        rc, out, _ = run(
            f"echo | openssl s_client -connect {shlex.quote(DOMAIN)}:443 "
            f"-servername {shlex.quote(DOMAIN)} 2>/dev/null | openssl x509 -noout -enddate"
        )
        if rc == 0 and out.strip().startswith("notAfter="):
            exp_line = out.strip().split("=", 1)[-1].strip()

    if not exp_line:
        fail("Could not determine certificate expiration.")
        results["CERT_EXPIRY"] = False
        return False

    try:
        days_left, exp_dt = parse_notafter_to_days(exp_line)
    except Exception as e:
        fail(f"Failed to parse cert date '{exp_line}': {e}")
        results["CERT_EXPIRY"] = False
        return False

    if days_left < 0:
        fail(f"Certificate EXPIRED {abs(days_left)} days ago (expires: {exp_dt}).")
        ok_result = False
    elif days_left < WARN_DAYS:
        warn(f"Certificate will expire in {days_left} days (expires: {exp_dt}).")
        ok_result = True
    else:
        ok(f"Certificate valid for {days_left} more days (expires: {exp_dt}).")
        ok_result = True

    results["CERT_EXPIRY"] = ok_result
    results["_cert_days_left"] = days_left
    return ok_result


def test_https_external(results):
    if not SIMULATE_EXTERNAL:
        results["HTTPS_EXTERNAL"] = True
        return True
    header("Simulated external HTTPS (curl --resolve to public IP)")
    pub_ip = results.get("_pub_ip", "")
    if not pub_ip:
        fail("No public IP available; skipping external simulation.")
        results["HTTPS_EXTERNAL"] = False
        return False

    rc, out, _ = run(
        [
            "curl",
            "-sS",
            "-m",
            str(CURL_TIMEOUT),
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--resolve",
            f"{DOMAIN}:443:{pub_ip}",
            f"https://{DOMAIN}/",
        ]
    )
    code = out.strip() if rc == 0 else ""
    if code in {"200", "301", "302", "401", "403"}:
        ok(f"HTTPS answered with HTTP {code} at {DOMAIN} (forced to {pub_ip}).")
        results["HTTPS_EXTERNAL"] = True
        return True

    fail(f"No HTTPS answer (code '{code or 'timeout'}').")
    results["HTTPS_EXTERNAL"] = False
    return False


# ====================== REPAIR ORCHESTRATION ==================== #
def _parse_args():
    p = argparse.ArgumentParser(
        description="Plex + Nginx health checks (DNS repair inline)"
    )
    p.add_argument(
        "--repair",
        choices=["never", "on-fail", "always"],
        default="never",
        help="when to attempt repairs (default: never)",
    )
    return p.parse_args()


def _collect_failures(results):
    """DNS_MATCH est critique au même titre que les autres tests."""
    failures = []
    for k in TESTS:
        if results.get(k) is False:
            failures.append(k)
    return failures


def _run_repairs(mode: str, failed_tests, results):
    """Réparations intégrées : DNS_MATCH seulement. Le reste = notice pro."""
    if mode == "never":
        return

    # always => tenter même si pas de fails; ici seul DNS a une implémentation
    targets = failed_tests if mode == "on-fail" else (failed_tests or ["DNS_MATCH"])

    for t in targets:
        if t == "DNS_MATCH":
            pub = results.get("_pub_ip", "") or get_public_ip()
            if not pub:
                fail("DNS repair aborted: cannot determine public IP.")
                continue
            repaired = repair_dns(pub)
            if not repaired:
                # déjà loggé dans repair_dns
                pass
        else:
            repair_generic(t)


# ============================== MAIN ============================ #
def main():
    args = _parse_args()

    results = {}

    # Ordre important (DNS avant HTTPS pour cohérence logs)
    test_preflight(results)
    test_conf_present(results)
    test_nginx_t(results)
    host, port = extract_upstream()
    results["UPSTREAM_FROM_CONF"] = True
    test_upstream(results, host, port)
    test_dns_match(results)
    test_cert_expiry(results)
    test_https_external(results)

    failing = _collect_failures(results)

    if not failing:
        ok("All critical checks passed.")
        _discord_send("🟢 **plex_online**: all critical checks passed.")
    else:
        fail("One or more checks failed: " + ", ".join(failing))
        _discord_send(f"🔴 **plex_online**: failing tests → {', '.join(failing)}")

    _run_repairs(args.repair, failing, results)

    # code de sortie
    sys.exit(0 if not failing else 2)


if __name__ == "__main__":
    main()
