#!/usr/bin/env python3
"""
Plex + Nginx (Docker) healthcheck

What it verifies:
  1) nginx-proxy has /etc/nginx/conf.d/plex.conf
  2) nginx -t succeeds in the container
  3) Extracts proxy_pass from plex.conf and checks Plex /identity (HTTP 200)
  4) DuckDNS domain IP == current public IP (curl ifconfig.me)
  5) Certificate files exist and are not expired (days remaining)
  6) Optional: HTTPS reachability "as from Internet" using curl --resolve
  7) Optional: Port publication for 80/443 from docker inspect

No external Python deps; uses subprocess to call docker/curl/openssl/dig.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone

# --------------------------- USER SETTINGS --------------------------- #
# Adjust these values to match your setup if needed.
CONTAINER = os.environ.get("CONTAINER", "nginx-proxy")                  # Name of the Nginx container
DOMAIN = os.environ.get("DOMAIN", "plex-robert.duckdns.org")            # Your DuckDNS domain
CONF_PATH = os.environ.get("CONF_PATH", "/etc/nginx/conf.d/plex.conf")  # Path to plex.conf inside container
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")  # Let's Encrypt path inside container
DNS_RESOLVER = os.environ.get("DNS_RESOLVER", "1.1.1.1")                # Resolver used by dig/nslookup
CURL_TIMEOUT = int(os.environ.get("CURL_TIMEOUT", "10"))                 # Seconds for curl timeouts
SIMULATE_EXTERNAL = os.environ.get("SIMULATE_EXTERNAL", "1") == "1"     # Try curl --resolve to public IP
CHECK_PORT_MAPPING = os.environ.get("CHECK_PORT_MAPPING", "1") == "1"   # Inspect 80/443 publication
WARN_DAYS = int(os.environ.get("WARN_DAYS", "15"))                       # Warn if cert expires in <WARN_DAYS
# -------------------------------------------------------------------- #

# Simple colored output helpers for readability
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

# Run a local command and return (rc, out, err)
def run(cmd, timeout=None):
    """
    Execute a command locally.
    `cmd` can be a list or a string. Returns (returncode, stdout, stderr).
    """
    if isinstance(cmd, str):
        shell = True
    else:
        shell = False
    try:
        proc = subprocess.run(
            cmd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            text=True,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

# Run a command inside the container via docker exec
def docker_exec(args, timeout=None):
    """
    Execute a command inside the Nginx container.
    `args` is a list of command tokens inside the container.
    """
    return run(["docker", "exec", "-i", CONTAINER] + args, timeout=timeout)

# Ensure required CLI tools are available on host
def require(cmd):
    if shutil.which(cmd) is None:
        fail(f"Missing required command on host: {cmd}")
        return False
    return True

def docker_container_running(name):
    rc, out, _ = run(["docker", "ps", "--format", "{{.Names}}"])
    if rc != 0:
        return False
    return any(line.strip() == name for line in out.splitlines())

def check_conf_presence():
    header("Check nginx config presence")
    # List directory to confirm access and presence of plex.conf
    rc, out, err = docker_exec(["ls", "-l", "/etc/nginx/conf.d"])
    if rc != 0:
        fail(f"Cannot list /etc/nginx/conf.d in container: {err or out}")
        return False

    # Verify plex.conf exists
    rc, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(CONF_PATH)}"])
    if rc == 0:
        ok(f"Found {CONF_PATH} in container.")
        return True
    else:
        fail(f"Missing {CONF_PATH} in container.")
        return False

def check_nginx_syntax():
    header("Check nginx config syntax (nginx -t)")
    rc, out, err = docker_exec(["nginx", "-t"])
    if rc == 0:
        ok("nginx -t: syntax OK")
        return True
    else:
        fail(f"nginx -t reported an error:\n{out}\n{err}")
        return False

def extract_upstream_from_conf():
    header("Extract upstream from plex.conf")
    # Grep the first proxy_pass http line, then return the URL
    cmd = [
        "sh", "-lc",
        f"awk '/proxy_pass[[:space:]]+http/{{print $2}}' {shlex.quote(CONF_PATH)} | head -n1 | tr -d ';'"
    ]
    rc, out, err = docker_exec(cmd)
    upstream_url = out.strip() if rc == 0 else ""
    if not upstream_url:
        warn(f"Could not find proxy_pass in {CONF_PATH}. Falling back to default 192.168.3.39:32400")
        return ("192.168.3.39", "32400")

    # Remove scheme and path to get host:port
    no_scheme = re.sub(r"^https?://", "", upstream_url)
    no_path = no_scheme.split("/", 1)[0]
    if ":" in no_path:
        host, port = no_path.split(":", 1)
    else:
        host, port = no_path, "80"  # default if no port specified
    ok(f"Detected upstream target: {host}:{port}")
    return (host, port)

def test_plex_upstream(host, port):
    header("Test Plex upstream (/identity) from inside container")
    # 200 OK is expected from /identity
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
    header("DuckDNS IP vs current public IP")
    # Try dig first
    if shutil.which("dig"):
        rc, out, err = run(["dig", "+short", DOMAIN, f"@{DNS_RESOLVER}"])
        duck_ip = out.splitlines()[-1].strip() if rc == 0 and out else ""
    else:
        # Fallback to nslookup
        rc, out, err = run(["nslookup", DOMAIN, DNS_RESOLVER])
        duck_ip = ""
        if rc == 0 and out:
            for line in out.splitlines():
                if line.strip().startswith("Address:"):
                    duck_ip = line.split("Address:")[-1].strip()

    if not duck_ip:
        fail(f"Unable to resolve {DOMAIN} via {DNS_RESOLVER}.")
    else:
        ok(f"{DOMAIN} resolves to: {duck_ip}")

    # Public IP from ifconfig.me (IPv4)
    rc, out, err = run(["curl", "-sS", "-4", "ifconfig.me"])
    pub_ip = out.strip() if rc == 0 and out else ""
    if not pub_ip:
        fail("Unable to fetch current public IP from ifconfig.me.")
    else:
        ok(f"Current public IP: {pub_ip}")

    # Compare
    if duck_ip and pub_ip:
        if duck_ip == pub_ip:
            ok("DuckDNS IP matches current public IP.")
            match = True
        else:
            fail(f"DuckDNS IP ({duck_ip}) does NOT match current public IP ({pub_ip}). Update DuckDNS or your updater.")
            match = False
    else:
        match = False

    return duck_ip, pub_ip, match

def check_cert_files_and_expiry():
    header("Check certificate files and expiration")
    # Verify files exist
    rc1, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/fullchain.pem"])
    rc2, _, _ = docker_exec(["sh", "-lc", f"test -f {shlex.quote(LE_PATH)}/privkey.pem"])
    if rc1 == 0 and rc2 == 0:
        ok(f"Found cert files under {LE_PATH} (fullchain.pem & privkey.pem).")
    else:
        warn(f"Cert files not found at {LE_PATH}. HTTPS may fail.")
        return False

    # Get expiration date from inside container using openssl
    rc, out, err = docker_exec([
        "sh", "-lc",
        f"openssl x509 -enddate -noout -in {shlex.quote(LE_PATH)}/fullchain.pem | cut -d= -f2"
    ])
    if rc != 0 or not out.strip():
        warn("Could not read certificate expiration with openssl.")
        return False

    exp_raw = out.strip()  # e.g., "Nov  5 12:00:00 2025 GMT"
    # Normalize double-space in day (e.g., "Nov  5" -> "Nov 5")
    exp_norm = re.sub(r"\s{2,}", " ", exp_raw)

    try:
        # Parse to datetime; openssl prints in English "GMT"
        exp_dt = datetime.strptime(exp_norm, "%b %d %H:%M:%S %Y %Z")
        now = datetime.now(timezone.utc)
        # Convert exp_dt to aware UTC (it already is "GMT", treat as UTC)
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        delta_days = int((exp_dt - now).total_seconds() // 86400)
    except Exception as e:
        warn(f"Failed to parse certificate date '{exp_raw}': {e}")
        return False

    if delta_days < 0:
        fail(f"Certificate EXPIRED {abs(delta_days)} days ago (expires: {exp_dt}).")
        return False
    elif delta_days < WARN_DAYS:
        warn(f"Certificate will expire in {delta_days} days (expires: {exp_dt}).")
        return True
    else:
        ok(f"Certificate valid for {delta_days} more days (expires: {exp_dt}).")
        return True

def simulate_external_https(pub_ip):
    if not SIMULATE_EXTERNAL or not pub_ip:
        return True  # Nothing to do / not a failure
    header("Simulated external HTTPS (curl --resolve to public IP)")
    # This does not require hairpin NAT; it forces SNI + IP to your public address
    # Success codes vary: 200/301/302/401/403 all prove "something" is answering.
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

def check_port_publication():
    if not CHECK_PORT_MAPPING:
        return True
    header("Check published ports (docker inspect)")
    rc, out, err = run(["docker", "inspect", CONTAINER])
    if rc != 0 or not out:
        warn(f"docker inspect failed: {err or out}")
        return False
    try:
        data = json.loads(out)[0]
        ports = data["NetworkSettings"]["Ports"] or {}
    except Exception as e:
        warn(f"Could not parse docker inspect output: {e}")
        return False

    # Expect 80/tcp and 443/tcp to be published/bound
    ok80 = False
    ok443 = False

    def fmt_bindings(binding_list):
        if not binding_list:
            return "NOT PUBLISHED"
        return ", ".join(f"{b.get('HostIp','') or '*'}:{b.get('HostPort','')}" for b in binding_list)

    b80 = ports.get("80/tcp")
    b443 = ports.get("443/tcp")
    info(f"80/tcp bindings:  {fmt_bindings(b80)}")
    info(f"443/tcp bindings: {fmt_bindings(b443)}")

    if b80 and all("HostPort" in b for b in b80):
        ok80 = True
    if b443 and all("HostPort" in b for b in b443):
        ok443 = True

    if ok80 and ok443:
        ok("Both 80/tcp and 443/tcp appear to be published.")
        return True
    else:
        warn("One or both ports (80/443) are not published. "
             "Ensure your compose/service exposes and maps these ports.")
        return False

def main():
    # Basic preflight checks on the host
    header("Preflight")
    all_ok = True
    for cmd in ("docker", "curl",):
        if not require(cmd):
            all_ok = False
    if not all_ok:
        sys.exit(2)

    # Check container running
    if not docker_container_running(CONTAINER):
        fail(f"Container '{CONTAINER}' is not running.")
        sys.exit(2)
    else:
        ok(f"Container '{CONTAINER}' is running.")

    # 1) plex.conf present
    if not check_conf_presence(): all_ok = False

    # 2) nginx -t
    if not check_nginx_syntax(): all_ok = False

    # 3) extract upstream + test Plex
    host, port = extract_upstream_from_conf()
    if not test_plex_upstream(host, port): all_ok = False

    # 4) DNS vs public IP
    duck_ip, pub_ip, match = resolve_duckdns_ip()
    if not match: all_ok = False

    # 5) Cert presence + expiry
    if not check_cert_files_and_expiry(): all_ok = False

    # 6) Simulate external HTTPS (optional)
    if not simulate_external_https(pub_ip): all_ok = False

    # 7) Check port publication (optional)
    if not check_port_publication(): all_ok = False

    print()
    if all_ok:
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
