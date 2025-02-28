#!/bin/bash

# Load environment variables from .env file
ENV_FILE="$(dirname "$0")/../.env"  # Assumes .env is at {ROOT}
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo -e "[Error]: \e[31mCRITICAL\e[0m - .env file not found. Please create it with ROOT path."
    exit 1
fi

# Color codes for status
GREEN="\e[32m"
ORANGE="\e[33m"
RED="\e[31m"
RESET="\e[0m"

# Define container names from .env if available
NGINX_CONTAINER="nginx-proxy"
VPN_CONTAINER="vpn"

check_nginx() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Nginx is running smoothly."

    # 1️⃣ Check if the Nginx container is running
    if ! docker ps --format "{{.Names}}" | grep -q "$NGINX_CONTAINER"; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx container ($NGINX_CONTAINER) is not running."
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 2️⃣ Validate Nginx configuration inside the container
    NGINX_CONFIG_CHECK=$(docker exec "$NGINX_CONTAINER" nginx -t 2>&1)
    if echo "$NGINX_CONFIG_CHECK" | grep -q "test is successful"; then
        echo -e "[Nginx]: ${GREEN}OK${RESET} - Nginx configuration is valid."
    else
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx configuration error: $(echo "$NGINX_CONFIG_CHECK" | tail -n 1)"
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi

    # 3️⃣ Check if Nginx is listening on expected ports
    if sudo netstat -tulnp | grep -qE ":80|:443"; then
        echo -e "[Nginx]: ${GREEN}OK${RESET} - Ports 80 and 443 are listening on the host."
    else
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Nginx is not listening on expected ports (80, 443) on the host."
        echo -e "[Nginx]: $STATUS - $MSG"
        return
    fi
}

check_vpn() {
    STATUS="${GREEN}OK${RESET}"
    MSG="VPN is running smoothly."

    # 1️⃣ Check if the VPN container is running
    if ! docker ps --format "{{.Names}}" | grep -q "$VPN_CONTAINER"; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="VPN container ($VPN_CONTAINER) is not running."
        echo -e "[VPN]: $STATUS - $MSG"
        return
    fi

    # 2️⃣ Check if VPN tunnel exists
    VPN_TUNNEL=$(docker exec "$VPN_CONTAINER" ip a | grep tun0)
    if [[ -z "$VPN_TUNNEL" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="VPN tunnel (tun0) is missing in the container."
        echo -e "[VPN]: $STATUS - $MSG"
        return
    fi

    # 3️⃣ Check external IP (should NOT match host IP)
    HOST_IP=$(curl -s https://ipinfo.io/ip)
    VPN_IP=$(docker exec "$VPN_CONTAINER" curl -s https://ipinfo.io/ip)

    if [[ "$HOST_IP" == "$VPN_IP" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="VPN is NOT working! External IP is still the same as the host ($HOST_IP)."
        echo -e "[VPN]: $STATUS - $MSG"
        return
    fi

    echo -e "[VPN]: ${GREEN}OK${RESET} - VPN is running, External IP: $VPN_IP."

    # 4️⃣ Test VPN connectivity
    if ! docker exec "$VPN_CONTAINER" ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="VPN is up but cannot reach external internet."
        echo -e "[VPN]: $STATUS - $MSG"
        return
    fi

    echo -e "[VPN]: ${GREEN}OK${RESET} - VPN connection is working."
}

check_server_health() {
    CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}')
    RAM_USAGE=$(free | awk '/Mem:/ {printf "%.2f", $3/$2 * 100}')
    DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')

    STATUS="${GREEN}OK${RESET}"
    MSG="Everything is running smoothly."

    if (( $(echo "$CPU_USAGE > 80" | bc -l) )); then
        STATUS="${ORANGE}WARNING${RESET}"
        MSG="High CPU usage: ${CPU_USAGE}%."
    fi
    if (( $(echo "$RAM_USAGE > 85" | bc -l) )); then
        STATUS="${ORANGE}WARNING${RESET}"
        MSG="High RAM usage: ${RAM_USAGE}%."
    fi
    if (( DISK_USAGE > 90 )); then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Low disk space: ${DISK_USAGE}% used."
    fi

    echo -e "[Server Health]: $STATUS - $MSG"
}

# Run checks
check_nginx
check_vpn
check_server_health