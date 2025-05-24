import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")
webhook = os.getenv("DISCORD_WEBHOOK")

if not webhook:
    print("No webhook configured.")
    exit()

msg = input("Enter message to send to Discord: ")

try:
    response = requests.post(webhook, json={"content": msg})
    if response.status_code == 204:
        print("Message sent.")
    else:
        print(f"Failed: HTTP {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
