#!/bin/bash
# chmod +x down.sh

# Check if Docker Compose services are running
if docker-compose ps | grep -q "Up"; then
    echo "[INFO] Docker Compose services are running. Shutting down safely..."

    # Stop Docker Compose services
    docker-compose down || { echo "[ERROR] Docker-compose down failed"; exit 1; }

    echo "[INFO] Docker Compose services have been shut down successfully."
else
    echo "[INFO] Docker Compose services are already stopped."
fi
