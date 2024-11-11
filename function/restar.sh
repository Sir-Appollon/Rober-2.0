#!/bin/bash

# Execute the first script (down.sh)
echo "Running down.sh..."
if ./down.sh; then
    echo "down.sh completed successfully."
else
    echo "Warning: down.sh failed. Exiting."
    exit 1
fi

# Execute the second script (up_docker.sh) only if down.sh succeeded
echo "Running up_docker.sh..."
if ./up_docker.sh; then
    echo "up_docker.sh completed successfully."
else
    echo "Warning: up_docker.sh failed. Exiting."
    exit 1
fi
