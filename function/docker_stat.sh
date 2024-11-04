#!/bin/bash

# Capture the output of docker stats, analyze and interpret it
output=$(docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemPerc}} {{.NetIO}} {{.BlockIO}}" | awk 'NR > 0 {print $0}')

high_cpu_threshold=80.0
high_mem_threshold=70.0

echo "Analyzing Docker container resource usage..."

while IFS= read -r line; do
    container_name=$(echo $line | awk '{print $1}')
    cpu_usage=$(echo $line | awk '{gsub("%", "", $2); print $2}')
    mem_usage=$(echo $line | awk '{gsub("%", "", $3); print $3}')
    net_io=$(echo $line | awk '{print $4}')
    block_io=$(echo $line | awk '{print $5}')
    
    # CPU analysis
    if (( $(echo "$cpu_usage > $high_cpu_threshold" | bc -l) )); then
        echo "Alert: Container '$container_name' is using high CPU ($cpu_usage%). Consider checking its processes."
    elif (( $(echo "$cpu_usage < 5.0" | bc -l) )); then
        echo "Note: Container '$container_name' is idle with low CPU usage ($cpu_usage%)."
    fi
    
    # Memory analysis
    if (( $(echo "$mem_usage > $high_mem_threshold" | bc -l) )); then
        echo "Warning: Container '$container_name' is using high memory ($mem_usage%). Check for memory-intensive processes or leaks."
    fi

    # Network I/O and Block I/O analysis
    echo "Container '$container_name' has Network I/O: $net_io and Block I/O: $block_io."
    echo "   - Ensure these values align with expected data traffic and disk usage."
done <<< "$output"

echo "Resource usage analysis completed."
