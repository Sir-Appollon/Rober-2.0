"""
File: discord_notify.py
Purpose: Send messages to a Discord channel using a webhook.

Inputs:
- Environment variable: DISCORD_WEBHOOK
- Message string passed to send_discord_message()

Outputs:
- Sends POST request to Discord Webhook
- Optionally prints debug messages if mode == "debug"

Triggered Files/Services:
- Called by monitoring and diagnostic scripts to report status or errors.
"""

import os
import requests
from dotenv import load_dotenv
import time

# Mode: "normal" or "debug"
mode = "debug"

# Load environment variables from standard paths
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../../.env")

# Retrieve webhook URL
discord_webhook = os.getenv("DISCORD_WEBHOOK")

def send_discord_message(content):
    """
    Sends a message to the configured Discord webhook.
    If in debug mode, prints status code and errors.
    """
    if not discord_webhook:
        if mode == "debug":
            print("[DEBUG - discord_notify.py] DISCORD_WEBHOOK not set.")
        return

    try:
        response = requests.post(discord_webhook, json={"content": content})
        if mode == "debug":
            print(f"[DEBUG - discord_notify.py] Discord response: {response.status_code} - {response.text}")

        if response.status_code == 429:  # Rate limited
            retry = response.json().get("retry_after", 1)
            if mode == "debug":
                print(f"[DEBUG - discord_notify.py] Rate limited. Retrying after {retry} seconds.")
            time.sleep(float(retry))

    except Exception as e:
        if mode == "debug":
            print(f"[DEBUG - discord_notify.py] Discord exception: {e}")

    time.sleep(0.5)  # Anti-flood delay
