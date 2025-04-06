#!/bin/bash

# 1. Load environment variables from .env file
ENV_FILE="$(dirname "$0")/../.env"
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo -e "[Error]: \e[31mCRITICAL\e[0m - .env file not found. Please create it at project ROOT."
    exit 1
fi

# 2. Extract domain name (remove protocol and trailing slash)
CLEAN_DOMAIN=$(echo "$DOMAIN" | sed -e 's~https\?://~~' -e 's:/$::')

# 3. Get current public IP
CURRENT_IP=$(curl -s ifconfig.me)

# 4. Get IP from DuckDNS record
DUCK_IP=$(dig +short "$CLEAN_DOMAIN")

# 5. Compare both IPs
echo "Current public IP : $CURRENT_IP"
echo "DuckDNS IP        : $DUCK_IP"

if [[ "$CURRENT_IP" == "$DUCK_IP" ]]; then
    echo -e "\e[32m✔ IPs match. No update needed.\e[0m"
    exit 0
else
    echo -e "\e[33m⚠ IP mismatch detected!\e[0m"
    read -p "Do you want to update DuckDNS to $CURRENT_IP ? (y/n) " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo "Updating DuckDNS..."
        curl -s "https://www.duckdns.org/update?domains=$CLEAN_DOMAIN&token=$DUCKDNS_TOKEN&ip=" -o ~/duckdns.log
        echo -e "\e[32m✔ Update sent. Check ~/duckdns.log for details.\e[0m"
    else
        echo -e "\e[34m↪ Skipped update.\e[0m"
    fi
fi
