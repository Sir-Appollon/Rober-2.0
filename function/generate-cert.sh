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

# 3. Check certbot availability
CERTBOT_CMD=$(command -v certbot)
if [[ -z "$CERTBOT_CMD" ]]; then
    echo -e "\e[31m[ERROR] certbot is not installed.\e[0m"
    echo "→ Install it with: sudo apt install certbot"
    exit 1
fi

# 4. Generate certificate
echo -e "\e[36m→ Generating Let's Encrypt certificate for $CLEAN_DOMAIN\e[0m"

sudo certbot certonly --standalone \
  --preferred-challenges http \
  --config-dir "$ROOT/config/nginx/letsencrypt" \
  --work-dir "$ROOT/config/nginx/letsencrypt/tmp" \
  --logs-dir "$ROOT/config/nginx/letsencrypt/log" \
  -d "$CLEAN_DOMAIN" \
  --email "paul.emilejen@gmail.com" \  # ← remplace ici aussi si tu veux automatiser
  --agree-tos \
  --non-interactive

# 5. Success or failure
if [[ -f "$ROOT/config/nginx/letsencrypt/live/$CLEAN_DOMAIN/fullchain.pem" ]]; then
  echo -e "\n\e[32m✔ Certificate successfully created at:\e[0m $ROOT/config/nginx/letsencrypt/live/$CLEAN_DOMAIN/"
else
  echo -e "\n\e[31m✖ Certificate generation failed.\e[0m"
fi
