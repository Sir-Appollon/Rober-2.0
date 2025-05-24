import os
import requests
from dotenv import load_dotenv

# Load environment variables from common Docker and host paths
# Try container path first, fallback to local path
if not load_dotenv(dotenv_path="/app/.env"):
    load_dotenv(dotenv_path="../.env")

# Get the webhook from environment
discord_webhook = os.getenv("DISCORD_WEBHOOK")
print("[DEBUG] DISCORD_WEBHOOK loaded as:", discord_webhook)

def send_discord_message(content):
    if not discord_webhook:
        print("[DEBUG] No DISCORD_WEBHOOK found. Skipping message.")
        return
    try:
        print("[DEBUG] Sending message to Discord...")
        response = requests.post(discord_webhook, json={"content": content})
        print(f"[DEBUG] Discord response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[DEBUG] Exception sending Discord message: {e}")
