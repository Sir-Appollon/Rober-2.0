#!/bin/bash

# Load environment variables from .env file
ENV_FILE="$(dirname "$0")/../.env"  # Assumes .env is at {ROOT}
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo -e "[Error]: ${RED}CRITICAL${RESET} - .env file not found. Please create it with ROOT path."
    exit 1
fi

# Color codes for status
GREEN="\e[32m"
ORANGE="\e[33m"
RED="\e[31m"
RESET="\e[0m"

check_nginx() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Everything is running smoothly"
    DOMAIN="robert2-0.duckdns.org"
    CONFIG_PATH="${ROOT}/config/nginx/Plexconf/nginx.conf"  # Dynamic path

    # 1. Check if Nginx process is running
    if ! pgrep -x "nginx" > /dev/null; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is not running"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 2. Validate Nginx configuration using the dynamic path
    NGINX_CONFIG_CHECK=$(nginx -t -c "$CONFIG_PATH" 2>&1)
    if [[ $? -ne 0 ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx configuration error: $(echo "$NGINX_CONFIG_CHECK" | tail -n 1)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 3. Check if Nginx is listening on expected ports
    HTTP_PORT=$(netstat -tulnp | grep ":80 " | grep nginx)
    HTTPS_PORT=$(netstat -tulnp | grep ":443 " | grep nginx)

    if [[ -z "$HTTP_PORT" && -z "$HTTPS_PORT" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is not listening on expected ports (80, 443)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 4. Check SSL Certificate expiration
    SSL_EXPIRY=$(echo | openssl s_client -servername $DOMAIN -connect $DOMAIN:443 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)

    if [[ -z "$SSL_EXPIRY" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Failed to retrieve SSL certificate for $DOMAIN"
    else
        EXPIRY_DATE=$(date -d "$SSL_EXPIRY" +%s)
        CURRENT_DATE=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_DATE - CURRENT_DATE) / 86400 ))  # Ensure integer division

        if (( DAYS_LEFT <= 7 )); then
            STATUS="${ORANGE}MINOR ISSUE${RESET}"
            MSG="SSL certificate for $DOMAIN is expiring in $DAYS_LEFT days"
        fi
    fi

    # 5. Check if the external URL is accessible
    HTTP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" https://$DOMAIN)

    if [[ "$HTTP_RESPONSE" -ne 200 ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is running, but $DOMAIN is not accessible (Response: $HTTP_RESPONSE)"
    fi

    echo -e "[Nginx]: $STATUS - $MSG"
}

# Run Nginx check
check_nginx
