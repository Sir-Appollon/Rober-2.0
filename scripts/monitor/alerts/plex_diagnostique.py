import socket
import ssl
import subprocess
import requests
from datetime import datetime

DUCKDNS_DOMAIN = "yourname.duckdns.org"  # ← à personnaliser
NGINX_CONTAINER = "nginx"  # ← le nom de ton conteneur NGINX

def check_duckdns_ip():
    try:
        duckdns_ip = socket.gethostbyname(DUCKDNS_DOMAIN)
        public_ip = requests.get("https://api.ipify.org").text.strip()
        print(f"[DuckDNS] DNS IP       : {duckdns_ip}")
        print(f"[DuckDNS] Public IP    : {public_ip}")
        return duckdns_ip == public_ip
    except Exception as e:
        print(f"[DuckDNS] Error: {e}")
        return False

def check_ssl_certificate(domain):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                subject = dict(x[0] for x in cert['subject'])
                not_after_str = cert['notAfter']
                not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                expires_in = (not_after - datetime.utcnow()).days
                print(f"[SSL] CN         : {subject.get('commonName', '')}")
                print(f"[SSL] Expire dans : {expires_in} jours")
                return expires_in > 0
    except Exception as e:
        print(f"[SSL] Error: {e}")
        return False

def check_nginx_config_docker(container_name):
    try:
        result = subprocess.run(
            ["docker", "exec", container_name, "nginx", "-t"],
            capture_output=True, text=True
        )
        print("[NGINX] stdout:")
        print(result.stdout.strip())
        print("[NGINX] stderr:")
        print(result.stderr.strip())
        return result.returncode == 0
    except Exception as e:
        print(f"[NGINX] Error: {e}")
        return False


if __name__ == "__main__":
    print("==== DuckDNS Check ====")
    duckdns_ok = check_duckdns_ip()
    print(f"→ DuckDNS ok: {duckdns_ok}\n")

    print("==== SSL Certificate Check ====")
    ssl_ok = check_ssl_certificate(DUCKDNS_DOMAIN)
    print(f"→ SSL ok: {ssl_ok}\n")

    print("==== NGINX Config Check (Docker) ====")
    nginx_ok = check_nginx_config_docker(NGINX_CONTAINER)
    print(f"→ NGINX config ok: {nginx_ok}\n")

    if all([duckdns_ok, ssl_ok, nginx_ok]):
        print("✅ Tout est fonctionnel.")
    else:
        print("❌ Problème détecté.")
