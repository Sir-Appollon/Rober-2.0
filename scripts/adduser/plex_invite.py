import os
import requests

PLEX_TOKEN = os.getenv("PLEX_TOKEN")
PLEX_USERNAME = os.getenv("PLEX_USERNAME")


def invite_user(email):
    headers = {
        "X-Plex-Token": PLEX_TOKEN,
        "Accept": "application/json",
    }

    payload = {
        "shared_server[email]": email,
        "shared_server[invited_id]": "",
        "shared_server[server_id]": "",  # Fill with your real server ID
        "shared_server[library_section_ids][]": "all",
    }

    plex_server_id = "YOUR_SERVER_ID"  # ← Replace this
    url = f"https://plex.tv/api/servers/{plex_server_id}/shared_servers"

    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.status_code, response.text
    except Exception as e:
        return 500, str(e)
