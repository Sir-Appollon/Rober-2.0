check_nginx() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Everything is running smoothly"
    DOMAIN="robert2-0.duckdns.org"
    CONFIG_PATH="/etc/nginx/conf.d/nginx.conf"  # Path inside the container
    NGINX_CONTAINER="nginx-proxy"  # Make sure this is correctly set!


    # 1. Check if the Docker container is running
    if ! docker ps --format "{{.Names}}" | grep -q "$NGINX_CONTAINER"; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx container ($NGINX_CONTAINER) is not running"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 2. Validate Nginx configuration inside the container (ignore warnings)
    NGINX_CONFIG_CHECK=$(docker exec "$NGINX_CONTAINER" nginx -t 2>&1)
    
    if echo "$NGINX_CONFIG_CHECK" | grep -q "test is successful"; then
        echo -e "[Nginx]: ${GREEN}OK${RESET} - Nginx configuration is valid"
    else
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx configuration error: $(echo "$NGINX_CONFIG_CHECK" | tail -n 1)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 3. Check if Nginx is listening on expected ports
    HTTP_PORT=$(docker exec "$NGINX_CONTAINER" netstat -tulnp | grep ":80 " | grep nginx)
    HTTPS_PORT=$(docker exec "$NGINX_CONTAINER" netstat -tulnp | grep ":443 " | grep nginx)

    if [[ -z "$HTTP_PORT" && -z "$HTTPS_PORT" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is not listening on expected ports (80, 443)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 4. Check SSL Certificate expiration inside the container
    SSL_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    SSL_EXPIRY=$(docker exec "$NGINX_CONTAINER" openssl x509 -enddate -noout -in "$SSL_PATH" 2>/dev/null | cut -d= -f2)

    if [[ -z "$SSL_EXPIRY" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Failed to retrieve SSL certificate for $DOMAIN inside the container"
    else
        EXPIRY_DATE=$(date -d "$SSL_EXPIRY" +%s)
        CURRENT_DATE=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_DATE - CURRENT_DATE) / 86400 ))

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
