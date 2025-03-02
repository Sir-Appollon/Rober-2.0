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

# Define container names
NGINX_CONTAINER="nginx-proxy"
VPN_CONTAINER="vpn"
PLEX_CONTAINER="plex-server"

# Hardcoded Plex URLs instead of using `.env`
PLEX_LOCAL_URL="http://localhost:32400/web"
PLEX_REMOTE_URL="https://robert2-0.duckdns.org/web"

### **🕒 Display Date and Time**
echo -e "\n\033[1m$(date '+%Y-%m-%d %H:%M:%S')\033[0m"

### **⚠️ Warn If Not Running as Root**
if [[ $EUID -ne 0 ]]; then
    echo -e "\e[33mWARNING: This script is not running with sudo/root. Some elements may not be available.\e[0m"
fi

check_plex_process() {
    if docker ps --format "{{.Names}}" | grep -q "$PLEX_CONTAINER"; then
        echo -e "[Plex]: ${GREEN}OK${RESET} - Plex process is running."
    else
        echo -e "[Plex]: ${RED}CRITICAL${RESET} - Plex process is not running!"
    fi
}

check_plex_database() {
    DB_PATH="/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
    
    DB_CHECK=$(docker exec "$PLEX_CONTAINER" sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>/dev/null)
    
    if [[ "$DB_CHECK" == "ok" ]]; then
        echo -e "[Plex]: ${GREEN}OK${RESET} - Plex database is healthy."
    else
        echo -e "[Plex]: ${RED}CRITICAL${RESET} - Plex database is corrupted!"
    fi
}

check_plex_library_updates() {
    LAST_UPDATE=$(docker exec "$PLEX_CONTAINER" stat -c %Y "/config/Library/Application Support/Plex Media Server/Logs/Plex Media Scanner.log" 2>/dev/null)
    CURRENT_TIME=$(date +%s)
    TIME_DIFF=$(( (CURRENT_TIME - LAST_UPDATE) / 3600 ))

    if [[ $TIME_DIFF -gt 24 ]]; then
        echo -e "[Plex]: ${ORANGE}WARNING${RESET} - Plex library has not been updated in over 24 hours."
    else
        echo -e "[Plex]: ${GREEN}OK${RESET} - Plex library was updated recently."
    fi
}

check_plex_transcoding_load() {
    TRANSCODE_CPU=$(docker exec "$PLEX_CONTAINER" top -bn1 | grep "Plex Transcoder" | awk '{cpu += $9} END {print cpu}')
    
    if [[ -z "$TRANSCODE_CPU" ]]; then
        echo -e "[Plex]: ${GREEN}OK${RESET} - No active transcoding."
    elif (( $(echo "$TRANSCODE_CPU > 80" | bc -l) )); then
        echo -e "[Plex]: ${ORANGE}WARNING${RESET} - High CPU usage due to transcoding (${TRANSCODE_CPU}%)."
    else
        echo -e "[Plex]: ${GREEN}OK${RESET} - Transcoding load is normal (${TRANSCODE_CPU}%)."
    fi
}

check_active_plex_streams() {
    STREAM_COUNT=$(docker exec "$PLEX_CONTAINER" curl -s "http://localhost:32400/status/sessions" | grep -o "<MediaContainer.*size=\"[0-9]*\"" | grep -o "[0-9]*")

    if [[ -z "$STREAM_COUNT" || "$STREAM_COUNT" -eq 0 ]]; then
        echo -e "[Plex]: ${GREEN}OK${RESET} - No active streams."
    else
        echo -e "[Plex]: ${GREEN}OK${RESET} - $STREAM_COUNT active stream(s) detected."
    fi
}

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
    OPEN_PORTS=$(netstat -tulnp 2>/dev/null | grep LISTEN | awk '{print $4}' | awk -F: '{print $NF}' | sort -n | uniq)

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
    CPU_USAGE=$(top -bn1 2>/dev/null | grep "Cpu(s)" | awk '{print $2 + $4}')
    RAM_USAGE=$(free 2>/dev/null | awk '/Mem:/ {printf "%.2f", $3/$2 * 100}')
    DISK_USAGE=$(df -h 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%')

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

# Run Plex-specific checks
check_plex_process
check_plex_database
check_plex_library_updates
check_plex_transcoding_load
check_active_plex_streams
check_web_status
