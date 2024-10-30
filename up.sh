#!/bin/bash
# chmod +x up.sh

# Pull updates if not skipped
if [ "$1" != "--skip-pull" ]; then
    git pull origin main || { echo "[ERROR] Git pull failed"; exit 1; }
    docker-compose pull || { echo "[ERROR] Docker-compose pull failed"; exit 1; }
fi

# Check if Docker Compose is already running
if docker-compose ps | grep -q "Up"; then
    echo "[INFO] Docker Compose services are already running."
else
    # Start Docker Compose services
    docker-compose up -d || { echo "[ERROR] Docker-compose up failed"; exit 1; }
fi

# Get public IP from the host
MY_IP=$(curl -s ifconfig.me)
if [ -z "$MY_IP" ]; then
    echo "[ERROR] Unable to retrieve host IP."
    exit 1
fi

# Get public IP from the VPN container
VPN_CONTAINER="vpn"
VPN_IP=$(docker exec $VPN_CONTAINER curl -s ifconfig.me)
if [ -z "$VPN_IP" ]; then
    echo "[ERROR] Unable to retrieve VPN container IP."
    docker-compose down
    exit 1
fi

# Check if both IPs are the same
if [ "$MY_IP" == "$VPN_IP" ]; then
    echo "$(date) [VPN:ERROR] The container's IP is the same as the host's IP. Shutting down..."
    sleep 1
    docker-compose down
else
    echo "$(date) [VPN:OK] IP is: $VPN_IP"
fi
