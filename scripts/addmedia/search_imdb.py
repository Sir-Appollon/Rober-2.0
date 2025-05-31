import requests

def search_imdb(title, content_type):
    api_key = "TON_API_KEY_OMDB"  # OMDb API Key
    url = f"http://www.omdbapi.com/?apikey={api_key}&t={title}&type={'movie' if content_type == 'movie' else 'series'}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if data["Response"] == "True":
            return {
                "title": data["Title"],
                "year": data["Year"],
                "imdb_id": data["imdbID"]
            }
    return None
