# pulsarr_export_watchlists.py
# Exporte les watchlists (films & séries) de toi ET de tes amis Plex
# via l’API de Pulsarr (pas besoin de token des amis, juste l’API Key Pulsarr).

import os
from pathlib import Path
from dotenv import load_dotenv
import requests
import pandas as pd

# Charger les variables d'environnement (.env)
for cand in [
    Path("/mnt/data/.env"),
    Path("/app/.env"),
    Path.cwd() / ".env",
    Path.home() / ".env",
]:
    if cand.is_file():
        load_dotenv(cand.as_posix())

BASE_URL = os.getenv("PULSARR_URL", "").rstrip("/")
API_KEY = os.getenv("PULSARR_API_KEY", "")


def main():
    if not BASE_URL or not API_KEY:
        print("❌ Manque PULSARR_URL ou PULSARR_API_KEY dans le .env")
        return

    sess = requests.Session()
    sess.headers.update({"X-API-Key": API_KEY, "Accept": "application/json"})

    def get_json(path):
        url = f"{BASE_URL}{path}"
        r = sess.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    rows = []

    # 1) Liste des utilisateurs
    try:
        try:
            users = get_json("/v1/users/users/list/with-counts")
        except Exception:
            users = get_json("/v1/users/users/list")

        # Normaliser la liste des utilisateurs
        user_list = users if isinstance(users, list) else users.get("data", [])
        for u in user_list:
            user_id = u.get("id") or u.get("_id") or u.get("userId") or u.get("user_id")
            user_name = (
                u.get("name")
                or u.get("username")
                or u.get("displayName")
                or str(user_id)
            )
            if not user_id:
                continue

            # 2) Watchlist de cet utilisateur
            try:
                wl = get_json(f"/v1/users/{user_id}/watchlist")
            except Exception as e:
                print(
                    f"[WARN] Impossible de récupérer la watchlist de {user_name}: {e}"
                )
                continue

            items = wl if isinstance(wl, list) else wl.get("items", [])
            for it in items:
                rows.append(
                    {
                        "user": user_name,
                        "title": it.get("title") or it.get("name", ""),
                        "year": it.get("year")
                        or it.get("releaseYear")
                        or it.get("firstAiredYear"),
                        "type": it.get("type") or it.get("mediaType"),
                        "tmdb_id": it.get("tmdbId") or it.get("ids", {}).get("tmdb"),
                        "tvdb_id": it.get("tvdbId") or it.get("ids", {}).get("tvdb"),
                        "imdb_id": it.get("imdbId") or it.get("ids", {}).get("imdb"),
                        "watchlisted_at": it.get("watchlistedAt")
                        or it.get("addedAt")
                        or it.get("createdAt"),
                        "source": it.get("source") or "pulsarr",
                    }
                )

    except requests.HTTPError as e:
        print(f"HTTP error de Pulsarr: {e}")
    except Exception as e:
        print(f"Erreur: {e}")

    # Sauvegarde CSV
    if rows:
        df = pd.DataFrame(rows)
        out_csv = "pulsarr_watchlists.csv"
        df.to_csv(out_csv, index=False, encoding="utf-8")
        print(f"✅ Export terminé : {out_csv} ({len(df)} entrées)")
    else:
        print(
            "⚠️ Aucune donnée récupérée. Vérifie Pulsarr et les watchlists des utilisateurs."
        )


if __name__ == "__main__":
    main()
