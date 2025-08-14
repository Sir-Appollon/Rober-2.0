#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plex_online.py
Health checks for Plex + Nginx (Docker). Can optionally call repair_plex.py.

USAGE (common)
  python3 scripts/tool/plex_online.py
  python3 scripts/tool/plex_online.py --repair on-fail
  python3 scripts/tool/plex_online.py --repair on-fail --apply
  python3 scripts/tool/plex_online.py --repair on-fail --allow-repairs CERT_EXPIRY,DNS_MATCH
  python3 scripts/tool/plex_online.py --json

ENV (defaults you can override)
  CONTAINER=nginx-proxy
  PLEX_CONTAINER=plex-server
  DOMAIN=plex-robert.duckdns.org
  CONF_PATH=/etc/nginx/conf.d/plex.conf
  LE_PATH=/etc/letsencrypt/live/${DOMAIN}
  DNS_RESOLVER=1.1.1.1
  UPSTREAM_FALLBACK_HOST=192.168.3.39
  UPSTREAM_FALLBACK_PORT=32400
  CURL_TIMEOUT=10
  SIMULATE_EXTERNAL=1           # 1 = test HTTPS via --resolve
  WARN_DAYS=15
  REPAIR_MODE=never             # never|on-fail|always (CLI overrides)
  ALLOW_REPAIRS=                # e.g. "CERT_EXPIRY,DNS_MATCH"
  DENY_REPAIRS=                 # e.g. "PLEX_UPSTREAM"
  REPAIR_SCRIPT=scripts/tool/repair_plex.py
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import socket

# --------------------------- SETTINGS --------------------------- #
CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")
PLEX_CONTAINER = os.environ.get("PLEX_CONTAINER", "plex-server")
DOMAIN = os.environ.get("DOMAIN", "plex-robert.duckdns.org")
CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")
DNS_RESOLVER = os.environ.get("DNS_RESOLVER", "1.1.1.1")  # conservé pour compat, non utilisé
UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")
CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))
SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"
WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))
# --------------------------------------------------------------- #

# Ordered list for reporting/filters
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

# --------------------------- UI helpers --------------------------- #
def color(tag, msg):
    codes = {"INFO":"\033[1;34m","OK":"\033[1;32m","WARN":"\033[1;33m","FAIL":"\033[1;31m","HDR":"\033[1;36m","END":"\033[0m"}
    return f"{codes.get(tag,'')}{msg}{codes['END']}"

def info(m): print(color("INFO","[INFO] "), m)
def ok(m):   print(color("OK","[ OK ] "), m)
def warn(m): print(color("WARN","[WARN] "), m)
def fail(m): print(color("FAIL","[FAIL] "), m)
def header(m): print(color("HDR", f"\n=== {m} ==="))

# --------------------------- proc helpers --------------------------- #
def run(cmd, timeout=None):
    """Run a command; returns (rc, stdout, stderr)."""
    shell = isinstance(cmd, str)
    p = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout or None)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def docker_exec(args, timeout=None):
    """docker exec into the nginx container."""
    return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)

def docker_container_running(name):
    rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
    return rc == 0 and any(line.strip() == name for line in out.splitlines())

def require(binname):
    return shutil.which(binname) is not None

# --------------------------- DNS/public IP helpers --------------------------- #
def resolve_a_records_py(domain: str) -> list[str]:
    """Resolve A records (IPv4) using Python only (no dig/nslookup needed)."""
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(domain, 0, family=socket.AF_UNSPEC)}
        # Keep only IPv4 for comparison to public IPv4
        return [a for a in addrs if a.count('.') == 3]
    except Exception:
        return []

def get_public_ip():
    """Get current public IPv4 via ifconfig.me (simple HTTP)."""
    rc, out, _ = run(["curl", "-sS", "-4", "ifconfig.me"])
    return out.strip() if rc == 0 else ""

# --------------------------- tests --------------------------- #
def test_preflight(results):
    header("Preflight")
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
    rc, out, _ = run(["curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}", url])
    if rc == 0 and out.strip() == "200":
        ok(f"Plex fallback upstream replied 200 on /identity ({UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}).")
    else:
        warn(f"Fallback Plex upstream test failed at {url} (code {out or 'n/a'}).")

    results["PREFLIGHT"] = ok_all
    return ok_all

def test_conf_present(results):
    header("Check nginx config presence")
    rc, _, err = docker_exec(["ls","-l","/etc/nginx/conf.d"])
    if rc != 0:
        fail(f"Cannot list conf.d: {err}")
        results["CONF_PRESENT"] = False
        return False

    rc, _, _ = docker_exec(["sh","-lc", f"test -f {shlex.quote(CONF_PATH)}"])
    if rc == 0:
        ok(f"Found {CONF_PATH} in container.")
        results["CONF_PRESENT"] = True
        return True

    fail(f"Missing {CONF_PATH} in container.")
    results["CONF_PRESENT"] = False
    return False

def test_nginx_t(results):
    header("Check nginx config syntax (nginx -t)")
    rc, out, err = docker_exec(["nginx","-t"])
    if rc == 0:
        ok("nginx -t: syntax OK")
        results["NGINX_TEST"] = True
        return True
    fail(f"nginx -t error:\n{out}\n{err}")
    results["NGINX_TEST"] = False
    return False

def extract_upstream():
    header("Extract upstream from plex.conf")
    rc, out, _ = docker_exec([
        "sh","-lc",
        f"awk '/proxy_pass[[:space:]]+http/{{print $2}}' {shlex.quote(CONF_PATH)} | head -n1 | tr -d ';'"
    ])
    url = out.strip() if rc == 0 else ""
    if not url:
        warn(f"No proxy_pass found. Using fallback {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}")
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
    rc, out, _ = docker_exec([
        "curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}",
        f"http://{host}:{port}/identity"
    ])
    if rc == 0 and out.strip() == "200":
        ok("Plex upstream replied 200 on /identity.")
        results["PLEX_UPSTREAM"] = True
        return True
    fail(f"Plex upstream test failed (HTTP {out or 'n/a'}).")
    results["PLEX_UPSTREAM"] = False
    return False

def test_dns_match(results):
    header("DuckDNS IP vs current public IP")
    # 1) Resolve A records (IPv4) for DOMAIN
    ips = resolve_a_records_py(DOMAIN)
    if not ips:
        warn("DNS resolve failed (Python).")
        results["DNS_MATCH"] = False
        return False

    info(f"Resolved {DOMAIN} -> {', '.join(ips)}")
    results["duckdns_ips"] = ips

    # 2) Current public IPv4 (cache if already computed)
    pub_ip = results.get("_pub_ip") or get_public_ip()
    if pub_ip:
        ok(f"Current public IP: {pub_ip}")
        results["_pub_ip"] = pub_ip
    else:
        warn("Unable to fetch current public IP.")
        results["DNS_MATCH"] = False
        return False

    # 3) Compare
    match = pub_ip in ips
    if match:
        ok(f"DuckDNS resolves to current public IP: {pub_ip}")
    else:
        warn(f"DuckDNS does not match current public IP ({pub_ip}); resolved={ips}")

    results["DNS_MATCH"] = match
    results["_duck_ip"] = ips[0] if ips else ""
    return match

def parse_notafter_to_days(exp_line):
    exp_norm = re.sub(r"\s{2,}", " ", exp_line)
    exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return int((exp_dt - now).total_seconds() // 86400), exp_dt

def test_cert_expiry(results):
    header("Check certificate files and expiration")
    # Files present?
    rc1, _, _ = docker_exec(["sh","-lc", f"test -f {shlex.quote(LE_PATH)}/fullchain.pem"])
    rc2, _, _ = docker_exec(["sh","-lc", f"test -f {shlex.quote(LE_PATH)}/privkey.pem"])
    if rc1 == 0 and rc2 == 0:
        ok(f"Found cert files under {LE_PATH} (fullchain.pem & privkey.pem).")
    else:
        warn(f"Cert files not found at {LE_PATH}.")
        results["CERT_EXPIRY"] = False
        return False

    # Try 1) in-container openssl, 2) host openssl via PEM, 3) remote s_client
    exp_line = ""
    has_in = (docker_exec(["sh","-lc","command -v openssl >/dev/null 2>&1"])[0] == 0)
    if has_in:
        rc, out, _ = docker_exec([
            "sh","-lc",
            f"openssl x509 -enddate -noout -in {shlex.quote(LE_PATH)}/fullchain.pem | cut -d= -f2"
        ])
        if rc == 0 and out.strip():
            exp_line = out.strip()

    if not exp_line and shutil.which("openssl"):
        rc, pem, _ = docker_exec(["sh","-lc", f"cat {shlex.quote(LE_PATH)}/fullchain.pem"])
        if rc == 0 and pem:
            p = subprocess.run(["openssl","x509","-enddate","-noout"],
                               input=pem, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0 and p.stdout.strip():
                exp_line = p.stdout.strip().split("=", 1)[-1].strip()

    if not exp_line and shutil.which("openssl"):
        rc, out, _ = run(
            f'echo | openssl s_client -connect {shlex.quote(DOMAIN)}:443 '
            f'-servername {shlex.quote(DOMAIN)} 2>/dev/null | openssl x509 -noout -enddate'
        )
        if rc == 0 and out.strip().startswith("notAfter="):
            exp_line = out.strip().split("=", 1)[-1].strip()

    if not exp_line:
        warn("Could not determine certificate expiration.")
        results["CERT_EXPIRY"] = False
        return False

    try:
        days_left, exp_dt = parse_notafter_to_days(exp_line)
    except Exception as e:
        warn(f"Failed to parse cert date '{exp_line}': {e}")
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
        warn("No public IP available; skipping external simulation.")
        results["HTTPS_EXTERNAL"] = False
        return False

    rc, out, _ = run([
        "curl","-sS","-m",str(CURL_TIMEOUT),"-o","/dev/null","-w","%{http_code}",
        "--resolve", f"{DOMAIN}:443:{pub_ip}",
        f"https://{DOMAIN}/"
    ])
    code = out.strip() if rc == 0 else ""
    if code in {"200","301","302","401","403"}:
        ok(f"HTTPS answered with HTTP {code} at {DOMAIN} (forced to {pub_ip}).")
        results["HTTPS_EXTERNAL"] = True
        return True

    warn(f"No HTTPS answer (code '{code or 'timeout'}').")
    results["HTTPS_EXTERNAL"] = False
    return False

# --------------------------- CLI / repair glue --------------------------- #
def _parse_args():
    p = argparse.ArgumentParser(description="Plex + Nginx health checks")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument("--apply", action="store_true", help="forward --apply to repair script")
    p.add_argument("--repair",
                   choices=["never","on-fail","always"],
                   default=os.environ.get("REPAIR_MODE", "never"),
                   help="when to call repair_plex.py (env: REPAIR_MODE)")
    p.add_argument("--allow-repairs",
                   default=os.environ.get("ALLOW_REPAIRS", ""),
                   help="comma-separated TEST KEYS allowed to be repaired")
    p.add_argument("--deny-repairs",
                   default=os.environ.get("DENY_REPAIRS", ""),
                   help="comma-separated TEST KEYS denied from repair")
    p.add_argument("--repair-script",
                   default=os.environ.get("REPAIR_SCRIPT",
                             os.path.join(os.path.dirname(__file__), "repair_plex.py")),
                   help="path to repair_plex.py")
    return p.parse_args()

def _filter_tests_for_repair(failing_tests, allow_csv, deny_csv):
    allow = {t.strip() for t in allow_csv.split(",") if t.strip()} if allow_csv else set()
    deny  = {t.strip() for t in deny_csv.split(",")  if t.strip()} if deny_csv  else set()
    chosen = list(failing_tests)
    if allow:
        chosen = [t for t in chosen if t in allow]
    if deny:
        chosen = [t for t in chosen if t not in deny]
    return chosen

def _call_repair(script_path, tests, apply_flag):
    if not tests:
        warn("No tests selected for repair.")
        return 0, "", ""
    info(f"Invoking repair script for: {', '.join(tests)}")
    cmd = ["python3", script_path, *tests]
    if apply_flag:
        cmd.append("--apply")
    return run(cmd)

# --------------------------- main --------------------------- #
def main():
    args = _parse_args()

    results = {}
    overall_ok = True

    # Run checks
    overall_ok &= test_preflight(results)
    overall_ok &= test_conf_present(results)
    overall_ok &= test_nginx_t(results)
    host, port = extract_upstream()
    results["UPSTREAM_FROM_CONF"] = True
    overall_ok &= test_upstream(results, host, port)
    overall_ok &= test_dns_match(results)
    overall_ok &= test_cert_expiry(results)
    overall_ok &= test_https_external(results)

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    failing = [k for k in TESTS if results.get(k) is False]

    # Decide on repairs
    if args.repair == "never":
        if overall_ok:
            ok("All critical checks passed.")
            sys.exit(0)
        else:
            fail("One or more checks failed.")
            info("Tip: use --repair on-fail --apply to attempt fixes.")
            sys.exit(2)

    if args.repair == "on-fail":
        if overall_ok:
            ok("All critical checks passed. No repairs executed (--repair on-fail).")
            sys.exit(0)
        to_repair = _filter_tests_for_repair(failing, args.allow_repairs, args.deny_repairs)

    elif args.repair == "always":
        # All repairable tests (including ones that passed), filtered
        repairable = {"CONF_PRESENT","NGINX_TEST","PLEX_UPSTREAM","DNS_MATCH","CERT_EXPIRY","HTTPS_EXTERNAL"}
        to_repair = _filter_tests_for_repair(
            [t for t in TESTS if t in repairable],
            args.allow_repairs, args.deny_repairs
        )

    # Call repair script
    rc, out, err = _call_repair(args.repair_script, to_repair, args.apply)
    if out: print(out)
    if err: print(err, file=sys.stderr)
    if rc != 0:
        warn(f"repair_plex.py exited with code {rc}")

    # Exit with success only if checks passed
    sys.exit(0 if overall_ok else 2)

if __name__ == "__main__":
    main()
