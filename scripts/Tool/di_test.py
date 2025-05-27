"""
File: send_message.py
Purpose: Send an arbitrary message to the Discord webhook for manual testing or quick alerts.

Inputs:
- Environment variable: DISCORD_WEBHOOK
- User input from command line

Outputs:
- Sends the message to Discord
- Prints status response to stdout

Triggered Files/Services:
- Discord Webhook API
"""

import os
import requests
from dotenv import load_dotenv

# Mode: "normal" or "debug"
mode = "normal"

# Load environment variables
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../../.env")

webhook = os.getenv("DISCORD_WEBHOOK")

if not webhook:
    print("[DEBUG - send_message.py] No webhook configured.") if mode == "debug" else print("No webhook configured.")
    exit(1)

msg = input("Enter message to send to Discord: ")

try:
    response = requests.post(webhook, json={"content": msg})
    if response.status_code == 204:
        print("[DEBUG - send_message.py] Message sent.") if mode == "debug" else print("Message sent.")
    else:
        print(f"[DEBUG - send_message.py] Failed: HTTP {response.status_code}") if mode == "debug" else print(f"Failed: HTTP {response.status_code}")
except Exception as e:
    print(f"[DEBUG - send_message.py] Error: {e}") if mode == "debug" else print(f"Error: {e}")
