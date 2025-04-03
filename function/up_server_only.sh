#!/bin/bash

# Start Plex and Nginx containers
echo "Starting Plex and Nginx containers..."
docker-compose up -d plex-server nginx

# Wait for 10 seconds
echo "Waiting for 10 seconds..."
sleep 10

# Define private and public IPs
PRIVATE_IP="192.168.1.1"  # Adjust this based on your network setup
PUBLIC_IP=$(curl -s ifconfig.me)  # Fetch public IP

# Check Plex accessibility
echo "Checking Plex accessibility..."
if curl -s --connect-timeout 5 http://$PRIVATE_IP:32400/web/ | grep -q "Plex"; then
    echo "✅ Plex is accessible from the private network."
else
    echo "❌ Plex is NOT accessible from the private network."
fi

if curl -s --connect-timeout 5 http://$PUBLIC_IP:32400/web/ | grep -q "Plex"; then
    echo "✅ Plex is accessible from the public network."
else
    echo "❌ Plex is NOT accessible from the public network."
fi
