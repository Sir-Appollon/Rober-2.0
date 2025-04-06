#!/bin/bash

# 1. Load .env from project root (relative to script)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/../.."  # remonte 2 niveaux depuis config/nginx/
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    echo "🔍 Loaded environment variables from .env"
else
    echo -e "[❌] \e[31m.env file not found at $ENV_FILE\e[0m"
    exit 1
fi

# 2. Extract domain name
CLEAN_DOMAIN=$(echo "$DOMAIN" | sed -e 's~https\?://~~' -e 's:/$::')

echo -e "\n🧪 Checking open ports:"
sudo ss -tulnp | grep -E ':80|:443|:32400' || echo "[❌] Required ports are not listening."

echo -e "\n🌐 Testing Plex local access (HTTP 302 expected):"
curl -I http://127.0.0.1:32400/web

CERT_PATH="$ROOT/config/nginx/letsencrypt/live/$CLEAN_DOMAIN/fullchain.pem"
echo -e "\n🔐 Checking SSL Certificate at: $CERT_PATH"
if [[ -f "$CERT_PATH" ]]; then
    openssl x509 -in "$CERT_PATH" -noout -subject -dates
else
    echo -e "[❌] Certificate not found!"
fi

echo -e "\n🌍 DuckDNS resolution check:"
DUCK_IP=$(dig +short "$CLEAN_DOMAIN")
CURRENT_IP=$(curl -s ifconfig.me)
echo "DuckDNS IP  : $DUCK_IP"
echo "Current IP  : $CURRENT_IP"
[[ "$DUCK_IP" == "$CURRENT_IP" ]] && echo "[✅] IPs match." || echo "[⚠️] IPs do not match."

echo -e "\n🔎 Testing local HTTPS via curl and Host header:"
curl -vk --resolve "$CLEAN_DOMAIN:443:127.0.0.1" https://"$CLEAN_DOMAIN" 2>&1 | grep -E "HTTP|subject=|issuer="

echo -e "\n✅ Done."
