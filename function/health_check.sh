#!/bin/bash

# Get the primary IP address of the host using ifconfig or ip
HOST=$(ip -4 addr show | awk '/inet / {print $2}' | cut -d/ -f1 | grep -v "127.0.0.1" | head -n 1)

# Alternative method using ip command (recommended for modern systems)
# HOST=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v "127.0.0.1" | head -n 1)

echo "Detected host IP: $HOST"

# Array of service names and their corresponding ports
declare -A services=(
    ["Plex"]=32400
    ["Sonarr"]=8989
    ["Radarr"]=7878
    ["Deluge"]=8112
    ["VPN"]=9091  # Adjust this if your VPN uses a different port for health check
    ["Jackett"]=9117
)

echo "Starting health check for Docker services..."

# Loop through each service and check if the port is open
for service in "${!services[@]}"; do
    port=${services[$service]}
    nc -z $HOST $port
    if [ $? -eq 0 ]; then
        echo "$service is running and reachable on port $port."
    else
        echo "$service is not reachable on port $port. Please check the service."
    fi
done

echo "Checking Docker container statuses..."

# Check for any "exited" containers
exited_containers=$(docker ps -a --filter "status=exited" --format "{{.Names}}")
if [ -z "$exited_containers" ]; then
    echo "No containers are in 'exited' status."
else
    echo "Warning: The following containers are in 'exited' status:"
    echo "$exited_containers"
fi

# Call the docker_stat.sh script for further analysis
echo "Running detailed Docker resource usage analysis..."
bash ./docker_stat.sh

# Check VPN IP against local IP
echo "Checking VPN connectivity by comparing Docker container IP with local IP..."

# Get the local IP
local_ip=$(curl -s https://ipinfo.io/ip)
echo "Local IP: $local_ip"

# Get the IP used by the VPN container (adjust 'vpn_container_name' as needed)
vpn_container_ip=$(docker exec vpn_container_name curl -s https://ipinfo.io/ip)

if [ "$vpn_container_ip" != "$local_ip" ]; then
    echo "VPN is active. The VPN container IP ($vpn_container_ip) differs from the local IP ($local_ip)."
else
    echo "Warning: VPN is not active. The VPN container IP matches the local IP."
fi

echo "Health check completed."
