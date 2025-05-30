# Pull updates if not skipped
if [ "$1" != "--skip-pull" ]; then
    git pull origin main || { echo "[ERROR] Git pull failed"; exit 1; }
    docker-compose pull || { echo "[ERROR] Docker compose pull failed"; exit 1; }
fi
