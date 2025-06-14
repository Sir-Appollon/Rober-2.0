# addmedia/radarr_sonarr_check.py

import os
import requests

RADARR_API_KEY = os.getenv("RADARR_API_KEY")
RADARR_URL = os.getenv("RADARR_URL", "http://localhost:7878")
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

async def is_already_in_radarr(imdb_id):
    try:
        url = f"{RADARR_URL}/api/v3/movie"
        headers = {"X-Api-Key": RADARR_API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return any(movie.get("imdbId") == imdb_id for movie in response.json())
    except Exception as e:
        print(f"[Radarr] Error checking: {e}")
    return False

async def is_already_in_plex(title):
    try:
        headers = {"X-Plex-Token": PLEX_TOKEN}
        response = requests.get(f"{PLEX_URL}/library/search", params={"query": title}, headers=headers)
        if response.status_code == 200 and title.lower() in response.text.lower():
            return True
    except Exception as e:
        print(f"[Plex] Error checking: {e}")
    return False
