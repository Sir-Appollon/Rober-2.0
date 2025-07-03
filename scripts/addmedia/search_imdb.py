import requests
import os

api_key = os.getenv("OMDB_API_KEY")


def search_imdb(title, content_type):
    search_url = f"http://www.omdbapi.com/?apikey={api_key}&s={title}&type={'movie' if content_type == 'movie' else 'series'}"
    search_response = requests.get(search_url)

    if search_response.status_code != 200:
        return []

    search_data = search_response.json()
    if search_data.get("Response") != "True":
        return []

    results = []
    for item in search_data.get("Search", []):
        imdb_id = item["imdbID"]
        details_url = f"http://www.omdbapi.com/?apikey={api_key}&i={imdb_id}&plot=short"
        details_response = requests.get(details_url)

        if details_response.status_code != 200:
            continue

        data = details_response.json()
        if data.get("Response") != "True":
            continue

        results.append(
            {
                "title": data["Title"],
                "year": data["Year"],
                "imdb_id": data["imdbID"],
                "ratings": data.get("Ratings", []),
                "poster": data.get("Poster", ""),
                "plot": data.get("Plot", ""),
            }
        )

    return results
