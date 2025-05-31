# search_imdb.py
import requests
import os

api_key = os.getenv("OMDB_API_KEY")


def search_imdb(title, content_type):
    url = f"http://www.omdbapi.com/?apikey={api_key}&t={title}&type={'movie' if content_type == 'movie' else 'series'}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if data["Response"] == "True":
            return {
                "title": data["Title"],
                "year": data["Year"],
                "imdb_id": data["imdbID"],
                "ratings": data.get("Ratings", []),
                "poster": data.get("Poster", "")
            }
    return None
