#!/bin/bash

# Color codes
GREEN="\e[32m"
ORANGE="\e[33m"
RED="\e[31m"
RESET="\e[0m"

check_server_health() {
    CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}')
    RAM_USAGE=$(free | awk '/Mem:/ {printf "%.2f", $3/$2 * 100}')
    DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
    LOAD_AVG=$(uptime | awk -F 'load average:' '{print $2}' | awk '{print $1}')
    TEMP=$(sensors | awk '/^Package id 0:/ {print $4}')

    STATUS="$GREEN Everything is running smoothly $RESET"
    
    if (( $(echo "$CPU_USAGE > 80" | bc -l) )); then
        STATUS="$ORANGE Minor issue - High CPU usage: ${CPU_USAGE}% $RESET"
    fi
    if (( $(echo "$RAM_USAGE > 85" | bc -l) )); then
        STATUS="$ORANGE Minor issue - High RAM usage: ${RAM_USAGE}% $RESET"
    fi
    if (( DISK_USAGE > 90 )); then
        STATUS="$RED Critical issue - Low disk space: ${DISK_USAGE}% used $RESET"
    fi

    echo -e "[Server Health]: $STATUS"
}

check_service_status() {
    SERVICE_NAME=$1
    PROCESS_NAME=$2
    DESCRIPTION=$3

    if pgrep -x "$PROCESS_NAME" > /dev/null; then
        echo -e "[$SERVICE_NAME]: $GREEN Everything is running smoothly $RESET"
    else
        echo -e "[$SERVICE_NAME]: $RED Critical issue - $DESCRIPTION is not running $RESET"
    fi
}

check_web_status() {
    SERVICE_NAME=$1
    URL=$2

    if curl -s --head --request GET $URL | grep "200 OK" > /dev/null; then
        echo -e "[$SERVICE_NAME]: $GREEN Web UI is responsive $RESET"
    else
        echo -e "[$SERVICE_NAME]: $RED Critical issue - Web UI is not responding $RESET"
    fi
}

check_docker_health() {
    CONTAINER_HEALTH=$(docker ps --format "{{.Names}} {{.State}}" | grep -E 'Restarting|Exited')

    if [ -z "$CONTAINER_HEALTH" ]; then
        echo -e "[Docker Health]: $GREEN Everything is running smoothly $RESET"
    else
        echo -e "[Docker Health]: $RED Critical issue - Some containers are in Restarting/Exited state: $CONTAINER_HEALTH $RESET"
    fi
}

check_vpn_status() {
    VPN_CONTAINER="vpn"
    EXTERNAL_IP=$(curl -s ifconfig.me)

    if docker ps --format "{{.Names}}" | grep -q "$VPN_CONTAINER"; then
        echo -e "[VPN Status]: $GREEN VPN container is running $RESET"
        echo -e "[VPN Status]: External IP: $EXTERNAL_IP"
    else
        echo -e "[VPN Status]: $RED Critical issue - VPN container is not running $RESET"
    fi
}

check_deluge_status() {
    if docker ps --format "{{.Names}}" | grep -q "deluge"; then
        echo -e "[Deluge Status]: $GREEN Deluge container is running $RESET"
        STALLED_TORRENTS=$(docker exec deluge deluge-console info | grep "State: Stalled" | wc -l)
        if [ "$STALLED_TORRENTS" -gt 0 ]; then
            echo -e "[Deluge Status]: $ORANGE Minor issue - $STALLED_TORRENTS stalled torrents detected $RESET"
        fi
    else
        echo -e "[Deluge Status]: $RED Critical issue - Deluge container is not running $RESET"
    fi
}

check_network() {
    OPEN_PORTS=$(netstat -tulnp | grep LISTEN | awk '{print $4}' | awk -F: '{print $NF}' | sort -n | uniq)
    INTERNET_TEST=$(ping -c 1 8.8.8.8 &> /dev/null && echo "Online" || echo "Offline")

    echo -e "[Network Traffic]: Open Ports: $OPEN_PORTS"
    if [ "$INTERNET_TEST" = "Online" ]; then
        echo -e "[Network Traffic]: $GREEN Internet connectivity is fine $RESET"
    else
        echo -e "[Network Traffic]: $RED Critical issue - No internet connectivity $RESET"
    fi
}

check_nginx() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Everything is running smoothly"
    DOMAIN="robert2-0.duckdns.org"

    # 1. Check if Nginx process is running
    if ! pgrep -x "nginx" > /dev/null; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is not running"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 2. Validate Nginx configuration
    NGINX_CONFIG_CHECK=$(nginx -t 2>&1)
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


# Run checks
check_server_health
check_service_status "Plex" "Plex Media Server" "Plex process"
check_web_status "Plex Web UI" "http://localhost:32400/web/index.html"
check_vpn_status
check_deluge_status
check_docker_health
check_network
check_nginx
