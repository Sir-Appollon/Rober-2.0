import os
import requests
from dotenv import load_dotenv
import time


# Load environment variables from common Docker and host paths
# Try container path first, fallback to local path
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

# Get the webhook from environment
discord_webhook = os.getenv("DISCORD_WEBHOOK")
#print("[DEBUG] DISCORD_WEBHOOK loaded as:", discord_webhook)

def send_discord_message(content):
    if not discord_webhook:
        return
    try:
        response = requests.post(discord_webhook, json={"content": content})
        print(f"[DEBUG] Discord response: {response.status_code} - {response.text}")
        if response.status_code == 429:
            retry = response.json().get("retry_after", 1)
            time.sleep(float(retry))
    except Exception as e:
        print(f"[DEBUG] Discord exception: {e}")
    time.sleep(0.5)  # small delay to reduce chance of flood
