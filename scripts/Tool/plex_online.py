#!/usr/bin/env python3
"""
Plex + Nginx (Docker) healthcheck (streamlined)

What it verifies:
  1) PRE-FLIGHT:
     - docker + curl availability
     - nginx-proxy container is running
     - Plex "online" quick test:
       a) If a Plex container name is provided, ensure it is running
       b) Try HTTP /identity against a fallback upstream (e.g., 192.168.3.39:32400)
  2) nginx-proxy has /etc/nginx/conf.d/plex.conf
  3) nginx -t succeeds in the container
  4) Extract proxy_pass from plex.conf and checks Plex /identity (HTTP 200)
  5) DuckDNS domain IP == current public IP (curl ifconfig.me)
  6) Certificate files exist and are not expired (days remaining)
  7) Optional: Simulated external HTTPS using curl --resolve (helpful for NAT/port-forward sanity)

Notes:
- No external Python dependencies; uses subprocess to call docker/curl/openssl/dig.
- The previous "Check published ports (docker inspect)" block was REMOVED per your request.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone

# --------------------------- USER SETTINGS --------------------------- #
# Adjust these values (or override via environment variables)
CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")                    # Nginx container name
PLEX_CONTAINER = os.environ.get("PLEX_CONTAINER", "plex-server")          # Plex container name (optional)
DOMAIN = os.environ.get("DOMAIN", "plex-robert.duckdns.org")              # Your DuckDNS domain
CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")    # Path to plex.conf inside Nginx container
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")    # Let's Encrypt path inside Nginx container
DNS_RESOLVER = os.environ.get("DNS_RESOLVER", "1.1.1.1")                  # Resolver used by dig/nslookup
CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))                  # Seconds for curl timeouts
SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"       # Try curl --resolve to public IP
WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))                        # Warn if cert expires in < WARN_DAYS
# Fallback Plex target for PRE-FLIGHT quick check (before reading plex.conf)
UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST", "192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT", "32400")
# -------------------------------------------------------------------- #

# -------------------------- Output helpers -------------------------- #
def color(tag, msg):
    colors = {
        "INFO": "\033[1;34m", "OK": "\033[1;32m", "WARN": "\033[1;33m", "FAIL": "\033[1;31m", "HDR": "\033[1;36m"
    }
    end = "\033[0m"
    return f"{colors.get(tag,'')}{msg}{end}"

def info(msg): print(color("INFO", "[INFO] "), msg)
def ok(msg):   print(color("OK",   "[ OK ] "), msg)
def warn(msg): print(color("WARN", "[WARN] "), msg)
def fail(msg): print(color("FAIL", "[FAIL] "), msg)
def header(msg): print(color("HDR", f"\n=== {msg} ==="))
# -------------------------------------------------------------------- #

# -------------------------- Shell helpers --------------------------- #
def run(cmd, timeout=None):
    """
    Execute a command on the host. `cmd` can be a list or string.
    Returns (returncode, stdout, stderr) with stdout/stderr stripped.
    """
    shell = isinstance(cmd, str)
    try:
        p = subprocess.run(
            cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False, text=True
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)

def docker_exec(args, timeout=None):
    """
    Execute a command inside the Nginx container via `docker exec`.
    Returns (rc, out, err).
    """
    return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)

def require(cmd):
    """
    Ensure a given binary exists on the host PATH.
    """
    if shutil.which(cmd) is None:
        fail(f"Missing required command on host: {cmd}")
        return False
    return True

def docker_container_running(name):
    """
    Check if a Docker container with an exact name is running.
    """
    rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
    if rc != 0:
        return False
    return any(line.strip() == name for line in out.splitlines())
# -------------------------------------------------------------------- #

# -------------------------- Health checks --------------------------- #
def preflight():
    """
    Preflight:
      - docker + curl must exist
      - nginx container must be running
      - Plex quick "online" check (container running + fallback /identity)
    """
    header("Preflight")
    all_ok = True

    # Basic tools available?
    for cmd in ("docker", "curl"):
        if not require(cmd):
            all_ok = False

    # Nginx container running?
    if not docker_container_running(CONTAINER):
        fail(f"Container '{CONTAINER}' is not running.")
        all_ok = False
    else:
        ok(f"Container '{CONTAINER}' is running.")

    # Plex container running? (best-effort; user can change name or skip)
    if PLEX_CONTAINER:
        if docker_container_running(PLEX_CONTAINER):
            ok(f"Plex container '{PLEX_CONTAINER}' is running.")
        else:
            warn(f"Plex container '{PLEX_CONTAINER}' not found/running (will still try HTTP fallback).")

    # Quick HTTP check against fallback upstream (before reading plex.conf)
    url = f"http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/identity"
    rc, out, err = run(["curl", "-sS", "-m", str(CURL_TIMEOUT), "-o", "/dev/null", "-w", "%{http_code}", url])
    code = out.strip() if rc == 0 else ""
    if code == "200":
        ok(f"Plex fallback upstream replied 200 on /identity ({UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}).")
    else:
        warn(f"Fallback Plex upstream test failed (HTTP {code or 'n/a'}) at {url}. "
             f"This is only a quick pre-check; the script will also test the upstream from plex.conf.")
    return all_ok

def check_conf_presence():
    """
    Confirm plex.conf exists in the container and is accessible.
    """
    header("Check nginx config presence")
    # Ensure we can list the directory
    rc, out, err = docker_exec(["ls", "-l", "/etc/nginx/conf.d"])
    if rc != 0:
        fail(f"Cannot list /etc/nginx/conf.d in container: {err or out}")
        return False

    # Confirm plex.conf exists
    rc, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(CONF_PATH)}"])
    if rc == 0:
        ok(f"Found {CONF_PATH} in container.")
        return True
    else:
        fail(f"Missing {CONF_PATH} in container.")
        return False

def check_nginx_syntax():
    """
    Run `nginx -t` inside the container.
    """
    header("Check nginx config syntax (nginx -t)")
    rc, out, err = docker_exec(["nginx", "-t"])
    if rc == 0:
        ok("nginx -t: syntax OK")
        return True
    else:
        fail(f"nginx -t reported an error:\n{out}\n{err}")
        return False

def extract_upstream_from_conf():
    """
    Parse the first proxy_pass http* line from plex.conf and extract host:port.
    """
    header("Extract upstream from plex.conf")
    cmd = [
        "sh", "-lc",
        f"awk '/proxy_pass[[:space:]]+http/{{print $2}}' {shlex.quote(CONF_PATH)} | head -n1 | tr -d ';'"
    ]
    rc, out, err = docker_exec(cmd)
    upstream_url = out.strip() if rc == 0 else ""
    if not upstream_url:
        # If not found, fallback to the preflight host:port
        warn(f"Could not find proxy_pass in {CONF_PATH}. Falling back to {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}")
        return (UPSTREAM_FALLBACK_HOST, UPSTREAM_FALLBACK_PORT)

    # Remove scheme and any path suffix to isolate host:port
    no_scheme = re.sub(r"^https?://", "", upstream_url)
    no_path = no_scheme.split("/", 1)[0]
    if ":" in no_path:
        host, port = no_path.split(":", 1)
    else:
        host, port = no_path, "80"
    ok(f"Detected upstream target: {host}:{port}")
    return (host, port)

def test_plex_upstream(host, port):
    """
    Hit the Plex /identity endpoint from inside the Nginx container.
    """
    header("Test Plex upstream (/identity) from inside container")
    url = f"http://{host}:{port}/identity"
    rc, out, err = docker_exec(["curl", "-sS", "-m", str(CURL_TIMEOUT), "-o", "/dev/null", "-w", "%{http_code}", url])
    code = out.strip() if rc == 0 else ""
    if code == "200":
        ok("Plex upstream replied 200 on /identity.")
        return True
    else:
        fail(f"Plex upstream test failed (HTTP {code or 'n/a'}). URL: {url}")
        return False

def resolve_duckdns_ip():
    """
    Compare DuckDNS A record vs current public IP.
    """
    header("DuckDNS IP vs current public IP")

    duck_ip = ""
    # Prefer dig if available, fallback to nslookup
    if shutil.which("dig"):
        rc, out, err = run(["sh", "-lc", f"dig +short {shlex.quote(DOMAIN)} @{shlex.quote(DNS_RESOLVER)}"])
        if rc == 0 and out.strip():
            duck_ip = out.splitlines()[-1].strip()
    else:
        rc, out, err = run(["nslookup", DOMAIN, DNS_RESOLVER])
        if rc == 0 and out:
            for line in out.splitlines():
                if line.strip().startswith("Address:"):
                    duck_ip = line.split("Address:")[-1].strip()

    if not duck_ip:
        fail(f"Unable to resolve {DOMAIN} via {DNS_RESOLVER}.")
    else:
        ok(f"{DOMAIN} resolves to: {duck_ip}")

    # Fetch current public IPv4
    rc, out, err = run(["curl", "-sS", "-4", "ifconfig.me"])
    pub_ip = out.strip() if rc == 0 and out else ""
    if not pub_ip:
        fail("Unable to fetch current public IP from ifconfig.me.")
    else:
        ok(f"Current public IP: {pub_ip}")

    # Compare values
    match = False
    if duck_ip and pub_ip:
        if duck_ip == pub_ip:
            ok("DuckDNS IP matches current public IP.")
            match = True
        else:
            fail(f"DuckDNS IP ({duck_ip}) does NOT match current public IP ({pub_ip}). Update DuckDNS or your updater.")
            match = False

    return duck_ip, pub_ip, match

def check_cert_files_and_expiry():
    """
    Verify cert files exist; read expiration (with a robust fallback if openssl
    is not installed inside the container).
    """
    header("Check certificate files and expiration")

    # Confirm cert files exist in container
    rc1, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/fullchain.pem"])
    rc2, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/privkey.pem"])
    if rc1 == 0 and rc2 == 0:
        ok(f"Found cert files under {LE_PATH} (fullchain.pem & privkey.pem).")
    else:
        warn(f"Cert files not found at {LE_PATH}. HTTPS may fail.")
        return False

    # Check if openssl exists inside container
    has_openssl = (docker_exec(["sh", "-lc", "command -v openssl >/dev/null 2>&1"])[0] == 0)

    if has_openssl:
        # Preferred path: use container's openssl
        rc, out, err = docker_exec([
            "sh", "-lc",
            f"openssl x509 -enddate -noout -in {shlex.quote(LE_PATH)}/fullchain.pem | cut -d= -f2"
        ])
        exp_line = out.strip() if rc == 0 else ""
    else:
        # Fallback: cat the PEM from container and pipe to host openssl
        if not require("openssl"):
            warn("No openssl in container AND host; cannot check expiration.")
            return False
        rc_cat, pem, err_cat = docker_exec(["sh", "-lc", f"cat {shlex.quote(LE_PATH)}/fullchain.pem"])
        if rc_cat != 0 or not pem:
            warn("Could not read certificate PEM from container for host-side parsing.")
            return False
        rc, out, err = run("openssl x509 -enddate -noout", timeout=CURL_TIMEOUT)
        if rc == 0:
            # When using host openssl via stdin, we must pipe the PEM
            # Re-run with input provided:
            p = subprocess.run(
                ["openssl", "x509", "-enddate", "-noout"],
                input=pem, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            exp_line = p.stdout.strip() if p.returncode == 0 else ""
        else:
            warn("Host openssl invocation failed; cannot parse expiration.")
            return False

    if not exp_line:
        warn("Could not read certificate expiration with openssl.")
        return False

    # exp_line typically looks like: "Nov  5 12:00:00 2025 GMT"
    exp_norm = re.sub(r"\s{2,}", " ", exp_line)
    try:
        exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z")
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_left = int((exp_dt - now).total_seconds() // 86400)
    except Exception as e:
        warn(f"Failed to parse certificate date '{exp_line}': {e}")
        return False

    if days_left < 0:
        fail(f"Certificate EXPIRED {abs(days_left)} days ago (expires: {exp_dt}).")
        return False
    elif days_left < WARN_DAYS:
        warn(f"Certificate will expire in {days_left} days (expires: {exp_dt}).")
        return True
    else:
        ok(f"Certificate valid for {days_left} more days (expires: {exp_dt}).")
        return True

def simulate_external_https(pub_ip):
    """
    Force SNI to your public IP using curl --resolve. Useful to validate that
    something responds on 443 even without hairpin NAT.
    Accept any of 200/301/302/401/403 as 'responding'.
    """
    if not SIMULATE_EXTERNAL or not pub_ip:
        return True
    header("Simulated external HTTPS (curl --resolve to public IP)")
    rc, out, err = run([
        "curl", "-sS", "-m", str(CURL_TIMEOUT), "-o", "/dev/null", "-w", "%{http_code}",
        "--resolve", f"{DOMAIN}:443:{pub_ip}",
        f"https://{DOMAIN}/"
    ])
    code = out.strip() if rc == 0 else ""
    if code in {"200", "301", "302", "401", "403"}:
        ok(f"HTTPS answered with HTTP {code} at {DOMAIN} (forced to {pub_ip}).")
        return True
    else:
        warn(f"HTTPS did not answer (code '{code or 'timeout'}'). "
             f"Check router port-forward 443→host:443 and host firewall (UFW).")
        return False
# -------------------------------------------------------------------- #

def main():
    overall_ok = True

    # 1) PRE-FLIGHT (now includes Plex online quick check)
    if not preflight():
        overall_ok = False

    # 2) plex.conf present
    if not check_conf_presence():
        overall_ok = False

    # 3) nginx -t
    if not check_nginx_syntax():
        overall_ok = False

    # 4) Extract upstream + test Plex from inside container
    host, port = extract_upstream_from_conf()
    if not test_plex_upstream(host, port):
        overall_ok = False

    # 5) DNS vs public IP
    _, pub_ip, match = resolve_duckdns_ip()
    if not match:
        overall_ok = False

    # 6) Cert presence + expiry (with container/host openssl fallback)
    if not check_cert_files_and_expiry():
        overall_ok = False

    # 7) Simulate external HTTPS (optional)
    if not simulate_external_https(pub_ip):
        overall_ok = False

    print()
    if overall_ok:
        ok("All critical checks passed.")
        sys.exit(0)
    else:
        fail("One or more checks failed. Review messages above.")
        sys.exit(2)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
        sys.exit(130)
