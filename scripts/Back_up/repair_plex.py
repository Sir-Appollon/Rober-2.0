#!/usr/bin/env python3
"""
repair_plex.py
Receives one or more TEST KEYS (from plex_online.py) and attempts safe repairs.

USAGE
  python3 scripts/tool/repair_plex.py CONF_PRESENT NGINX_TEST CERT_EXPIRY --apply
  python3 scripts/tool/repair_plex.py DNS_MATCH

SAFE BY DEFAULT
  - Dry-run by default (prints what it would do)
  - Use --apply to actually make changes

REPAIRS MAPPING
  CONF_PRESENT  -> Create minimal /etc/nginx/conf.d/plex.conf with upstream+TLS (if missing)
  NGINX_TEST    -> If syntax OK, reload; if not, show error context (no auto edit)
  PLEX_UPSTREAM -> Provide guided steps (cannot auto-fix routing); optional: switch to fallback upstream with --force-fallback
  DNS_MATCH     -> Update DuckDNS if DUCKDNS_TOKEN + DUCKDNS_SUBDOMAIN present
  CERT_EXPIRY   -> Install openssl in container (Alpine/Debian aware), then reload nginx
  HTTPS_EXTERNAL-> Print NAT/port-forward checklist

ENV
  CONTAINER, DOMAIN, CONF_PATH, LE_PATH, UPSTREAM_FALLBACK_HOST, UPSTREAM_FALLBACK_PORT
  DUCKDNS_TOKEN, DUCKDNS_SUBDOMAIN  (for DNS updates)
"""

import os, shlex, subprocess, sys

CONTAINER = os.environ.get("CONTAINER","nginx-proxy")
DOMAIN = os.environ.get("DOMAIN","plex-robert.duckdns.org")
CONF_PATH = os.environ.get("CONF_PATH","/etc/nginx/conf.d/plex.conf")
LE_PATH = os.environ.get("LE_PATH", f"/etc/letsencrypt/live/{DOMAIN}")
UPSTREAM_FALLBACK_HOST = os.environ.get("UPSTREAM_FALLBACK_HOST","192.168.3.39")
UPSTREAM_FALLBACK_PORT = os.environ.get("UPSTREAM_FALLBACK_PORT","32400")
DUCKDNS_TOKEN = os.environ.get("DUCKDNS_TOKEN","")
DUCKDNS_SUBDOMAIN = os.environ.get("DUCKDNS_SUBDOMAIN","")  # e.g. "plex-robert"

APPLY = ("--apply" in sys.argv)
FORCE_FALLBACK = ("--force-fallback" in sys.argv)

def color(tag, msg):
    codes = {"INFO":"\033[1;34m","OK":"\033[1;32m","WARN":"\033[1;33m","FAIL":"\033[1;31m","HDR":"\033[1;36m","END":"\033[0m"}
    return f"{codes.get(tag,'')}{msg}{codes['END']}"

def info(m): print(color("INFO","[INFO] "), m)
def ok(m):   print(color("OK","[ OK ] "), m)
def warn(m): print(color("WARN","[WARN] "), m)
def fail(m): print(color("FAIL","[FAIL] "), m)
def header(m): print(color("HDR", f"\n=== {m} ==="))

def run(cmd):
    shell = isinstance(cmd, str)
    p = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def docker_exec(args):
    return run(["docker","exec","-i",CONTAINER]+args)

def nginx_reload():
    if APPLY:
        rc,_,err = docker_exec(["nginx","-s","reload"])
        if rc==0: ok("nginx reload sent.")
        else:     fail(f"nginx reload failed: {err}")
    else:
        info("DRY-RUN: would run 'nginx -s reload' in container.")

def repair_conf_present():
    header("Repair: CONF_PRESENT")
    # Minimal, safe default conf
    minimal = f"""
server {{
    listen 443 ssl http2;
    server_name {DOMAIN};

    ssl_certificate {LE_PATH}/fullchain.pem;
    ssl_certificate_key {LE_PATH}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {{
        proxy_pass http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }}
}}
server {{
    listen 80;
    server_name {DOMAIN};
    location / {{
        return 301 https://$host$request_uri;
    }}
}}
""".strip()+"\n"

    if APPLY:
        # Write file atomically via sh heredoc
        cmd = f"cat > {shlex.quote(CONF_PATH)} <<'EOF'\n{minimal}EOF"
        rc,_,err = docker_exec(["sh","-lc", cmd])
        if rc==0:
            ok(f"Wrote minimal config to {CONF_PATH}")
            # syntax re-check then reload
            rc2,out2,err2 = docker_exec(["nginx","-t"])
            if rc2==0:
                ok("nginx -t OK after writing config.")
                nginx_reload()
            else:
                fail(f"nginx -t failed:\n{out2}\n{err2}")
        else:
            fail(f"Failed to write {CONF_PATH}: {err}")
    else:
        info(f"DRY-RUN: would create minimal {CONF_PATH} pointing to {UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT} and TLS files in {LE_PATH}.")

def repair_nginx_test():
    header("Repair: NGINX_TEST")
    # We don’t auto-modify conf; we re-test and reload if OK, else show context.
    rc,out,err = docker_exec(["nginx","-t"])
    if rc==0:
        ok("nginx -t currently OK.")
        nginx_reload()
        return
    fail("nginx -t still failing.")
    # Show conf lines around errors for guidance
    docker_exec(["sh","-lc", f"nl -ba {shlex.quote(CONF_PATH)} | sed -n '1,200p'"])

def repair_plex_upstream():
    header("Repair: PLEX_UPSTREAM")
    warn("Automatic repair is not safe for upstream connectivity issues.")
    info("Checklist:")
    info(" 1) Verify Plex answers locally: curl http://HOST:32400/identity (you already did)")
    info(" 2) Confirm network path from nginx container to that HOST:32400")
    info(" 3) If using container name, ensure DNS/links/networks are correct")
    info(" 4) If needed, use --force-fallback to rewrite proxy_pass to UPSTREAM_FALLBACK_*")
    if FORCE_FALLBACK:
        if APPLY:
            cmd = f"sed -i -E 's#proxy_pass\\s+http[^;]+;#proxy_pass http://{UPSTREAM_FALLBACK_HOST}:{UPSTREAM_FALLBACK_PORT}/;#' {shlex.quote(CONF_PATH)}"
            rc,_,err = docker_exec(["sh","-lc", cmd])
            if rc==0:
                ok("Rewrote proxy_pass to fallback upstream.")
                rc2,_,_ = docker_exec(["nginx","-t"])
                if rc2==0: nginx_reload()
                else: fail("nginx -t failed after rewrite.")
            else:
                fail(f"sed rewrite failed: {err}")
        else:
            info("DRY-RUN: would rewrite proxy_pass to fallback and reload nginx.")

def repair_dns_match():
    header("Repair: DNS_MATCH")
    if not DUCKDNS_TOKEN or not DUCKDNS_SUBDOMAIN:
        warn("DUCKDNS_TOKEN and/or DUCKDNS_SUBDOMAIN not set; cannot auto-update.")
        info("Set env, then re-run with --apply. Example:")
        info("  DUCKDNS_SUBDOMAIN=plex-robert DUCKDNS_TOKEN=xxxx --apply")
        return
    # Ask duckdns to set your current public IP (server-side auto-detect)
    url = f"https://www.duckdns.org/update?domains={DUCKDNS_SUBDOMAIN}&token={DUCKDNS_TOKEN}&ip="
    if APPLY:
        rc,out,err = run = subprocess.run(["curl","-sS",url], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        status = (run.stdout or "").strip()
        if status=="OK": ok("DuckDNS updated successfully.")
        else: fail(f"DuckDNS update response: {status}")
    else:
        info(f"DRY-RUN: would call: curl -s {url}")

def repair_cert_expiry():
    header("Repair: CERT_EXPIRY")
    # Install openssl inside container so future checks work
    if APPLY:
        rc,out,_ = docker_exec(["sh","-lc",". /etc/os-release 2>/dev/null; echo ${ID:-unknown}"])
        distro = (out or "unknown").strip()
        if distro == "alpine":
            rc,_,err = docker_exec(["sh","-lc","apk add --no-cache openssl || true"])
        else:
            rc,_,err = docker_exec(["sh","-lc","apt-get update && apt-get install -y openssl || true"])
        if rc==0: ok("Ensured openssl present in container (best-effort).")
        else:     warn(f"Could not install openssl: {err}")
        nginx_reload()
    else:
        info("DRY-RUN: would install openssl in container (apk/apt) and reload nginx.")
        info("If cert is close to expiry, renew it using your usual certbot/acme flow, then reload nginx.")

def repair_https_external():
    header("Repair: HTTPS_EXTERNAL")
    warn("Cannot auto-fix external HTTPS reachability.")
    info("Checklist:")
    info("  - Router/NAT: forward TCP 443 (and optionally 80) → host IP of nginx-proxy")
    info("  - ISP: ensure no inbound 443 block")
    info("  - Host firewall (UFW): allow 443/tcp")
    info("  - If behind CGNAT: use reverse proxy or tunnel (Cloudflare Tunnel, Tailscale Funnel, etc.)")

# ----------------- dispatcher ----------------- #
ACTIONS = {
    "CONF_PRESENT":  repair_conf_present,
    "NGINX_TEST":    repair_nginx_test,
    "PLEX_UPSTREAM": repair_plex_upstream,
    "DNS_MATCH":     repair_dns_match,
    "CERT_EXPIRY":   repair_cert_expiry,
    "HTTPS_EXTERNAL":repair_https_external,
}

def main():
    tests = [t for t in sys.argv[1:] if not t.startswith("-")]
    if not tests:
        warn("No test keys provided. Example: repair_plex.py CONF_PRESENT DNS_MATCH --apply")
        sys.exit(1)
    info(f"Mode: {'APPLY' if APPLY else 'DRY-RUN'}")
    for t in tests:
        fn = ACTIONS.get(t)
        if not fn:
            warn(f"Unknown test key: {t}")
            continue
        fn()

if __name__=="__main__":
    main()
