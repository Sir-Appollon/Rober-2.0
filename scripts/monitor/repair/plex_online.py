#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plex_online.py
Health checks for Plex + Nginx (Docker). Can optionally call repair_plex.py.

USAGE (common)
  python3 scripts/tool/plex_online.py
  python3 scripts/tool/plex_online.py --mode on-fail
  python3 scripts/tool/plex_online.py --mode on-fail --apply
  python3 scripts/tool/plex_online.py --mode on-fail --allow-repairs CERT_EXPIRY,DNS_MATCH
  python3 scripts/tool/plex_online.py --json
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
import urllib.request

# --------------------------- SETTINGS --------------------------- #
CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")
PLEX_CONTAINER = os.environ.get("PLEX_CONTAINER", "plex-server")

DOMAIN_RAW = os.environ.get("DOMAIN", "plex-robert.duckdns.org")
DOMAIN_HOST = re.sub(r"^https?://", "", DOMAIN_RAW).split("/")[0]
DOMAIN = DOMAIN_HOST

CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN_HOST}")
UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")
CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))
SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"
WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))

MODE_AUTO = os.environ.get("MODE_AUTO", "never").strip()

ALLOW_REPAIRS_ENV = os.environ.get("ALLOW_REPAIRS", "")
DENY_REPAIRS_ENV = os.environ.get("DENY_REPAIRS", "")
REPAIR_SCRIPT_ENV = os.environ.get(
    "REPAIR_SCRIPT", os.path.join(os.path.dirname(__file__), "repair_plex.py")
)

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
# --------------------------------------------------------------- #

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
def _discord_send(msg: str):
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
        pass


def color(tag, msg):
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
    print(color("INFO", "[INFO] "), m)


def ok(m):
    print(color("OK", "[ OK ] "), m)


def warn(m):
    print(color("WARN", "[WARN] "), m)
    _discord_send(f"⚠️ {m}")


def fail(m):
    print(color("FAIL", "[FAIL] "), m)
    _discord_send(f"❌ {m}")


def header(m):
    print(color("HDR", f"\n=== {m} ==="))


# --------------------------- proc helpers --------------------------- #
def run(cmd, timeout=None):
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


def docker_exec(args, timeout=None):
    return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)


def docker_container_running(name):
    rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
    return rc == 0 and any(line.strip() == name for line in out.splitlines())


def require(binname):
    return shutil.which(binname) is not None


# --------------------------- DNS/public IP helpers --------------------------- #
def _have_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _dig_a(domain: str, server: str, timeout=1.5, tries=1):
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


# --------------------------- tests --------------------------- #
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


def parse_notafter_to_days(exp_line):
    exp_norm = re.sub(r"\s{2,}", " ", exp_line)
    exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z").replace(
        tzinfo=timezone.utc
    )
    now = datetime.now(timezone.utc)
    return int((exp_dt - now).total_seconds() // 86400), exp_dt


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


# --------------------------- CLI / repair glue --------------------------- #
def _parse_args():
    p = argparse.ArgumentParser(description="Plex + Nginx health checks")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument(
        "--apply", action="store_true", help="forward --apply to repair script"
    )
    p.add_argument("--mode", choices=["never", "on-fail", "always"], default=MODE_AUTO)
    p.add_argument("--always", action="store_true")
    p.add_argument("--allow-repairs", default=ALLOW_REPAIRS_ENV)
    p.add_argument("--deny-repairs", default=DENY_REPAIRS_ENV)
    p.add_argument("--repair-script", default=REPAIR_SCRIPT_ENV)
    return p.parse_args()


def _filter_tests_for_repair(failing_tests, allow_csv, deny_csv):
    allow = (
        {t.strip() for t in allow_csv.split(",") if t.strip()} if allow_csv else set()
    )
    deny = {t.strip() for t in deny_csv.split(",") if t.strip()} if deny_csv else set()
    chosen = list(failing_tests)
    if allow:
        chosen = [t for t in chosen if t in allow]
    if deny:
        chosen = [t for t in chosen if t not in deny]
    return chosen


def _call_repair(script_path, tests, apply_flag):
    if not tests:
        warn("No tests selected for repair.")
        return
