#!/bin/bash

# 1. Load .env
ENV_FILE="$(dirname "$0")/.env"
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo -e "[❌] \e[31m.env file not found\e[0m"
    exit 1
fi

echo "🔍 Loading .env done."

# 2. Check required variables
if [[ -z "$ROOT" || -z "$DOMAIN" ]]; then
    echo -e "[❌] \e[31mROOT or DOMAIN is not defined in .env\e[0m"
    exit 1
fi

# 3. Extract clean domain
CLEAN_DOMAIN=$(echo "$DOMAIN" | sed -e 's~https\?://~~' -e 's:/$::')

echo -e "\n🧪 Checking port availability:"
sudo ss -tulnp | grep -E ':80|:443|:32400' || echo "[❌] Ports not found!"

# 4. Test Plex internal access
echo -e "\n🌐 Testing local Plex access..."
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:32400/web

# 5. Check Let's Encrypt cert
CERT_PATH="$ROOT/config/nginx/letsencrypt/live/$CLEAN_DOMAIN/fullchain.pem"
if [[ -f "$CERT_PATH" ]]; then
    echo -e "\n🔐 SSL certificate exists:"
    openssl x509 -in "$CERT_PATH" -noout -subject -dates
else
    echo -e "[❌] SSL certificate missing at: $CERT_PATH"
fi

# 6. DuckDNS resolution
echo -e "\n🌍 Checking DuckDNS record..."
DUCK_IP=$(dig +short "$CLEAN_DOMAIN")
CURRENT_IP=$(curl -s ifconfig.me)

echo "DuckDNS points to : $DUCK_IP"
echo "Public IP is      : $CURRENT_IP"

if [[ "$DUCK_IP" == "$CURRENT_IP" ]]; then
    echo "[✅] IPs match."
else
    echo "[⚠️] IP mismatch!"
fi

# 7. Test local HTTPS access to domain
echo -e "\n🔎 Testing local HTTPS with curl and Host override..."
curl -vk --resolve "$CLEAN_DOMAIN:443:127.0.0.1" https://"$CLEAN_DOMAIN" 2>&1 | grep -E "HTTP|subject=|issuer="

echo -e "\n✅ Health check finished.\n"
