import os
import socket
import requests
from datetime import datetime
from dotenv import load_dotenv

# Vérifie si l'environnement est déjà prêt (via Docker)
required_env_vars = ["DUCKDNS_TOKEN", "DOMAIN"]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
    if os.path.isfile(dotenv_path):
        load_dotenv(dotenv_path)
        print(f"[ENV] Chargé depuis {dotenv_path}")
    else:
        print(f"[ENV] Fichier .env introuvable à {dotenv_path}")
else:
    print("[ENV] Variables d’environnement déjà disponibles (Docker) ✅")

# === DuckDNS settings (extracted once) ===
duckdns_token = os.getenv("DUCKDNS_TOKEN")
domain_full = os.getenv("DOMAIN")

if not duckdns_token or not domain_full:
    print("[ERROR] DUCKDNS_TOKEN or DOMAIN missing in .env ❌")
    exit(1)

domain_full = domain_full.replace("https://", "").replace("/", "")
duckdns_domain = domain_full.split(".duckdns.org")[0]
NGINX_CONTAINER = "nginx-proxy"  # ← prêt pour plus tard si tu réactives nginx check

def check_duckdns_ip():
    try:
        duckdns_ip = socket.gethostbyname(domain_full)
        public_ip = requests.get("https://api.ipify.org").text.strip()
        print(f"[DuckDNS] DNS IP       : {duckdns_ip}")
        print(f"[DuckDNS] Public IP    : {public_ip}")

        if duckdns_ip == public_ip:
            print("[DuckDNS] IP already up-to-date ✅")
            return True
        else:
            print("[DuckDNS] IP mismatch — updating DuckDNS record... 🔄")
            update_url = f"https://www.duckdns.org/update?domains={duckdns_domain}&token={duckdns_token}&ip={public_ip}"
            response = requests.get(update_url).text.strip()

            if response == "OK":
                print("[DuckDNS] Successfully updated the IP 🎉")
                return True
            else:
                print(f"[DuckDNS] Failed to update IP ❌: response = {response}")
                return False

    except Exception as e:
        print(f"[DuckDNS] Error: {e}")
        return False

if __name__ == "__main__":
    print("==== DuckDNS Check ====")
    duckdns_ok = check_duckdns_ip()
    print(f"→ DuckDNS ok: {duckdns_ok}\n")



# def check_ssl_certificate(domain):
#     try:
#         context = ssl.create_default_context()
#         with socket.create_connection((domain, 443), timeout=10) as sock:
#             with context.wrap_socket(sock, server_hostname=domain) as ssock:
#                 cert = ssock.getpeercert()
#                 subject = dict(x[0] for x in cert['subject'])
#                 not_after_str = cert['notAfter']
#                 not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
#                 expires_in = (not_after - datetime.utcnow()).days
#                 print(f"[SSL] CN         : {subject.get('commonName', '')}")
#                 print(f"[SSL] Expire dans : {expires_in} jours")
#                 return expires_in > 0
#     except Exception as e:
#         print(f"[SSL] Error: {e}")
#         return False

# def test_nginx_config_inside_container(container_name):
#     try:
#         result = subprocess.run(
#             ["docker", "exec", container_name, "nginx", "-t"],
#             capture_output=True,
#             text=True
#         )
#         print("[NGINX] stdout:")
#         print(result.stdout.strip())
#         print("[NGINX] stderr:")
#         print(result.stderr.strip())
#         return result.returncode == 0
#     except Exception as e:
#         print(f"[NGINX] Error (docker exec): {e}")
#         return False



# if __name__ == "__main__":
#     print("==== DuckDNS Check ====")
#     duckdns_ok = check_duckdns_ip()
#     print(f"→ DuckDNS ok: {duckdns_ok}\n")

    # print("==== SSL Certificate Check ====")
    # ssl_ok = check_ssl_certificate(DUCKDNS_DOMAIN)
    # print(f"→ SSL ok: {ssl_ok}\n")

    # print("==== NGINX Config Check (Docker) ====")
    # nginx_ok = check_nginx_config_docker(NGINX_CONTAINER)
    # print(f"→ NGINX config ok: {nginx_ok}\n")

    # if all([duckdns_ok, ssl_ok, nginx_ok]):
    #     print("✅ Tout est fonctionnel.")
    # else:
    #     print("❌ Problème détecté.")
