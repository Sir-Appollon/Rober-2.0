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

# Load Plex domain from .env
PLEX_LOCAL_URL="http://localhost:32400/web"
PLEX_REMOTE_URL="https://robert2-0.duckdns.org/web"


check_web_status() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Plex is available locally and via the web."

    # 1️⃣ Check if Plex is available locally
    LOCAL_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -L "$PLEX_LOCAL_URL/index.html")
    if [[ "$LOCAL_RESPONSE" -ne 200 ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Plex is NOT accessible locally (Response: $LOCAL_RESPONSE)."
        echo -e "[Plex Web]: $STATUS - $MSG"
        return
    fi
    echo -e "[Plex Web]: ${GREEN}OK${RESET} - Plex is accessible locally."

    # 2️⃣ Check if Plex is accessible from the web
    REMOTE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -L "$PLEX_REMOTE_URL/index.html")
    if [[ "$REMOTE_RESPONSE" -ne 200 ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Plex is NOT accessible from the web (Response: $REMOTE_RESPONSE)."
        echo -e "[Plex Web]: $STATUS - $MSG"
        return
    fi
    echo -e "[Plex Web]: ${GREEN}OK${RESET} - Plex is accessible via the web."
}

check_network() {
    STATUS="${GREEN}OK${RESET}"
    MSG="Network connectivity is stable."

    # Check if key ports are open
    REQUIRED_PORTS=(22 53 80 443 631 7878 8112 8191 8989 9091 9117 32401 32600 36487 44075 61209)
    OPEN_PORTS=$(netstat -tulnp | grep LISTEN | awk '{print $4}' | awk -F: '{print $NF}' | sort -n | uniq)
    
    # Find unnecessary open ports
    UNNECESSARY_PORTS=()
    for port in $OPEN_PORTS; do
        if [[ ! " ${REQUIRED_PORTS[@]} " =~ " ${port} " ]]; then
            UNNECESSARY_PORTS+=("$port")
        fi
    done

    # Test internet connectivity
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo -e "[Network]: $STATUS - Internet connectivity is fine."
    else
        STATUS="${RED}CRITICAL${RESET}"
        MSG="No internet connectivity."
        echo -e "[Network]: $STATUS - $MSG"
        return
    fi

    # Show unnecessary open ports if any
    if [[ ${#UNNECESSARY_PORTS[@]} -gt 0 ]]; then
        STATUS="${ORANGE}WARNING${RESET}"
        MSG="Unnecessary open ports detected: ${UNNECESSARY_PORTS[*]}"
        echo -e "[Network]: $STATUS - $MSG"
    else
        echo -e "[Network]: ${GREEN}OK${RESET} - Only necessary ports are open."
    fi
}

check_docker_health() {
    STATUS="${GREEN}OK${RESET}"
    MSG="All containers are running smoothly."

    # Check for any unhealthy Docker containers
    UNHEALTHY_CONTAINERS=$(docker ps --format "{{.Names}} {{.State}}" | grep -E 'Restarting|Exited')

    if [[ -n "$UNHEALTHY_CONTAINERS" ]]; then
        STATUS="${RED}CRITICAL${RESET}"
        MSG="Some containers are in Restarting/Exited state: $UNHEALTHY_CONTAINERS."
        echo -e "[Docker Health]: $STATUS - $MSG"
        return
    fi

    echo -e "[Docker Health]: $STATUS - $MSG"
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
check_web_status
check_docker_health
check_network
check_server_health
