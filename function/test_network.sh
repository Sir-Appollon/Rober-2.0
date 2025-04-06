#!/bin/bash

echo "🔄 Loading environment variables..."
ENV_FILE="$(dirname "$0")/../.env"
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    echo "✅ Environment variables loaded."
else
    echo -e "[❌] .env file not found at $ENV_FILE"
    exit 1
fi

DOMAIN=$(echo "$DOMAIN" | sed -e 's~https\?://~~' -e 's:/$::')

echo ""
echo "🧪 Checking open ports (80, 443, 32400):"
sudo ss -tulnp | grep -E ':80|:443|:32400'

echo ""
echo "🌐 Testing Plex local access:"
curl -I http://127.0.0.1:32400/web

echo ""
echo "🔐 Checking SSL Certificate:"
CERT_PATH="$ROOT/config/nginx/letsencrypt/live/$DOMAIN/fullchain.pem"
if [[ -f "$CERT_PATH" ]]; then
    openssl x509 -in "$CERT_PATH" -noout -subject -dates
else
    echo "[❌] SSL Certificate not found at $CERT_PATH"
fi

echo ""
echo "🌍 DuckDNS resolution check:"
DUCK_IP=$(dig +short "$DOMAIN")
CURRENT_IP=$(curl -s ifconfig.me)
echo "DuckDNS IP  : $DUCK_IP"
echo "Current IP  : $CURRENT_IP"
if [[ "$DUCK_IP" == "$CURRENT_IP" ]]; then
    echo "[✅] IPs match."
else
    echo "[❌] IPs mismatch."
fi

echo ""
echo "🌐 Testing HTTPS via curl:"
curl -vk "https://$DOMAIN" --max-time 10

echo ""
echo "✅ All tests completed."
