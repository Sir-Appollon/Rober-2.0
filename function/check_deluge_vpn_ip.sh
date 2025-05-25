# Retrieve host's public IP
MY_IP=$(curl -s ifconfig.me)
if [ -z "$MY_IP" ]; then
    echo "[ERROR] Unable to retrieve host IP."
    exit 1
fi

# Retrieve VPN container's public IP
VPN_CONTAINER="vpn"
VPN_IP=$(docker exec $VPN_CONTAINER curl -s ifconfig.me)
if [ -z "$VPN_IP" ]; then
    echo "[ERROR] Unable to retrieve VPN container IP."
    docker compose down
    exit 1
fi

echo "Host IP: $MY_IP"
echo "VPN IP: $VPN_IP"

# Retry check up to 3 times
retries=3
success=0
for i in $(seq 1 $retries); do
    VPN_IP=$(docker exec $VPN_CONTAINER curl -s ifconfig.me)
    if [ "$MY_IP" = "$VPN_IP" ]; then
        echo "$(date) [VPN:ERROR] Attempt $i: IP leak detected — container using host IP."
        sleep 6
    else
        echo "$(date) [VPN:OK] Secure. Container IP: $VPN_IP"
        success=1
        break
    fi
done

if [ "$success" -eq 0 ]; then
    echo "$(date) [VPN:ERROR] All attempts failed. Shutting down..."
    docker compose down
    exit 1
fi


echo "VPN_IP: $VPN_IP"
echo "DELUGE_IP: $DELUGE_IP"
echo "HOST_IP: $MY_IP"
