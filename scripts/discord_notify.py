import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")
discord_webhook = os.getenv("DISCORD_WEBHOOK")

def send_discord_message(content):
    if not discord_webhook:
        return
    try:
        requests.post(discord_webhook, json={"content": content})
    except Exception:
        pass
