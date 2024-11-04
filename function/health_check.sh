#!/bin/bash

# Get the primary IP address of the host
HOST=$(ip -4 addr show | awk '/inet / {print $2}' | cut -d/ -f1 | grep -v "127.0.0.1" | head -n 1)

# Define an array of service names and their corresponding ports
declare -A services=(
    ["Plex"]=32400
    ["Sonarr"]=8989
    ["Radarr"]=7878
    ["Deluge"]=8112
    ["VPN"]=9091
    ["Jackett"]=9117
)

echo "Starting health check for Docker services..."

# Initialize a variable to track unreachable services
unreachable_services=()

# Loop through each service and check if the port is open
for service in "${!services[@]}"; do
    port=${services[$service]}
    nc -z $HOST $port
    if [ $? -ne 0 ]; then
        unreachable_services+=("$service")
    fi
done

# Check if there are any unreachable services and print the appropriate message
if [ ${#unreachable_services[@]} -eq 0 ]; then
    echo "All containers are up."
else
    echo "The following containers are not reachable: ${unreachable_services[@]}"
fi

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

# Get the IP used by the VPN container (adjust 'vpn' as needed)
vpn_container_ip=$(docker exec vpn curl -s https://ipinfo.io/ip)

if [ "$vpn_container_ip" != "$local_ip" ]; then
    echo "VPN is active. The VPN container IP ($vpn_container_ip) differs from the local IP ($local_ip)."
else
    echo "Warning: VPN is not active. The VPN container IP matches the local IP."
fi

echo "Health check completed."
