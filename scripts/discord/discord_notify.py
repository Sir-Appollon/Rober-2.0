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

# Load .env
print("[DEBUG - discord_notify.py.py] Attempting to load .env")
env_loaded = False
for p in [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
]:
    if load_dotenv(p):
        print(f"[DEBUG - discord_notify.py.py] Loaded environment file: {p}")
        env_loaded = True
        break
if not env_loaded:
    print("[DEBUG - discord_notify.py.py] No .env file found.")
else:
    print("[DEBUG - discord_notify.py] Environment variables loaded successfully")

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
