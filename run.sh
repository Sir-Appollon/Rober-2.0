#!/bin/bash

# Directory containing function files
function_dir="./function"

# Check if the directory exists
if [ ! -d "$function_dir" ]; then
    echo "The function directory could not be found. Please check the setup."
    exit 1
fi

# List all .sh files in the function directory
files=("$function_dir"/*.sh)

# Display menu options to the user
echo "What do you want to run?"
for i in "${!files[@]}"; do
    filename=$(basename "${files[$i]}")
    echo "$((i + 1)). ${filename}"
done
echo "$(( ${#files[@]} + 1 )). Exit"

# Read user input
read -p "Select an option (1-${#files[@]} or ${#files[@]} + 1 to exit): " choice

# Validate and run the selected script or exit
if [[ $choice -ge 1 && $choice -le ${#files[@]} ]]; then
    if ! bash "${files[$((choice - 1))]}"; then
        echo "There was a problem executing the file. Please check the script for errors."
    fi
elif [[ $choice -eq $(( ${#files[@]} + 1 )) ]]; then
    echo "Exiting the selection. Goodbye!"
    exit 0
else
    echo "Invalid option. Please run the script again and select a valid option."
fi
