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

# Define Nginx container name and domain
NGINX_CONTAINER="nginx-proxy"
DOMAIN="robert2-0.duckdns.org"

check_nginx() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Everything is running smoothly"

    # 1️⃣ Check if the Docker container is running
    if ! docker ps --format "{{.Names}}" | grep -q "$NGINX_CONTAINER"; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx container ($NGINX_CONTAINER) is not running"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 2️⃣ Validate Nginx configuration inside the container
    NGINX_CONFIG_CHECK=$(docker exec "$NGINX_CONTAINER" nginx -t 2>&1)
    
    if echo "$NGINX_CONFIG_CHECK" | grep -q "test is successful"; then
        echo -e "[Nginx]: ${GREEN}OK${RESET} - Nginx configuration is valid"
    else
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx configuration error: $(echo "$NGINX_CONFIG_CHECK" | tail -n 1)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 3️⃣ Check if Nginx is listening on expected ports
    if [[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' $NGINX_CONTAINER)" == "host" ]]; then
        if sudo netstat -tulnp | grep -qE ":80|:443"; then
            echo -e "[Nginx]: ${GREEN}OK${RESET} - Ports 80 and 443 are listening on the host"
        else
            STATUS="${RED}CRITICAL${RESET}"
            MSG="Nginx is not listening on expected ports (80, 443) on the host"
            echo -e "[Nginx]: $STATUS - $MSG"
            return
        fi
    else
        HTTP_PORT=$(docker exec "$NGINX_CONTAINER" netstat -tulnp | grep ":80 " | grep nginx)
        HTTPS_PORT=$(docker exec "$NGINX_CONTAINER" netstat -tulnp | grep ":443 " | grep nginx)

        if [[ -z "$HTTP_PORT" && -z "$HTTPS_PORT" ]]; then
            STATUS="${RED}CRITICAL${RESET}"
            MSG="Nginx is not listening on expected ports (80, 443)"
            echo -e "[Nginx]: $STATUS - $MSG"
            return
        fi
    fi

    # 4️⃣ Check SSL Certificate expiration (from the host, not Docker)
    SSL_EXPIRY=$(echo | openssl s_client -servername $DOMAIN -connect $DOMAIN:443 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)

    if [[ -z "$SSL_EXPIRY" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Failed to retrieve SSL certificate for $DOMAIN (checked from host)"
    else
        EXPIRY_DATE=$(date -d "$SSL_EXPIRY" +%s)
        CURRENT_DATE=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_DATE - CURRENT_DATE) / 86400 ))

        if (( DAYS_LEFT <= 7 )); then
            STATUS="${ORANGE}MINOR ISSUE${RESET}"
            MSG="SSL certificate for $DOMAIN is expiring in $DAYS_LEFT days"
        fi
    fi

    # 5️⃣ Check if the external URL is accessible (Use Plex Token for authentication)
    if [[ -z "$PLEX_TOKEN" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="PLEX_TOKEN is missing from .env. Cannot check external access."
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    HTTP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN?X-Plex-Token=$PLEX_TOKEN")

    if [[ "$HTTP_RESPONSE" -ne 200 ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is running, but $DOMAIN is not accessible (Response: $HTTP_RESPONSE)"
    fi

    echo -e "[Nginx]: $STATUS - $MSG"
}

# Run Nginx check
check_nginx
