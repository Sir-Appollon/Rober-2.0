#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Plex Watchlist -> Radarr/Sonarr (skip items already in Plex)
- Films -> Radarr
- Séries -> Sonarr

ENV attendus (dans .env):
  PLEX_URL, PLEX_TOKEN
  RADARR_URL, RADARR_API_KEY, RADARR_ROOT, RADARR_PROFILE (nom du profil)
  SONARR_URL, SONARR_API_KEY, SONARR_ROOT, SONARR_PROFILE (nom du profil)
  # Optionnels:
  DRY_RUN=0|1  (1 = ne fait qu'afficher)
  VERBOSE=0|1  (1 = logs détaillés)
"""

import os, re, json, time, sys
from pathlib import Path
import requests
from dotenv import load_dotenv
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

# ---------- ENV ----------
for cand in ["/app/.env", "/mnt/data/.env", str(Path.cwd()/".env")]:
    try:
        if Path(cand).is_file():
            load_dotenv(cand)
            break
    except Exception:
        pass

PLEX_URL   = os.getenv("PLEX_URL") or os.getenv("PLEX_SERVER")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")

RADARR_URL        = (os.getenv("RADARR_URL") or "").rstrip("/")
RADARR_API_KEY    = os.getenv("RADARR_API_KEY", "")
RADARR_ROOT       = os.getenv("RADARR_ROOT", "/mnt/media/Movies")
RADARR_PROFILE    = os.getenv("RADARR_PROFILE", "")   # ex: "HD-1080p"

SONARR_URL        = (os.getenv("SONARR_URL") or "").rstrip("/")
SONARR_API_KEY    = os.getenv("SONARR_API_KEY", "")
SONARR_ROOT       = os.getenv("SONARR_ROOT", "/mnt/media/TV")
SONARR_PROFILE    = os.getenv("SONARR_PROFILE", "")   # ex: "HD-1080p"

DRY_RUN   = os.getenv("DRY_RUN", "0") == "1"
VERBOSE   = os.getenv("VERBOSE", "1") == "1"

def log(msg): 
    print(msg, flush=True)

def v(msg):
    if VERBOSE:
        log(msg)

def die(msg, code=1):
    log(f"[FATAL] {msg}")
    sys.exit(code)

# ---------- HTTP helpers ----------
def sess_with_key(base_url, api_key):
    s = requests.Session()
    s.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})
    s.base_url = base_url
    return s

radarr = sess_with_key(RADARR_URL, RADARR_API_KEY) if RADARR_URL and RADARR_API_KEY else None
sonarr = sess_with_key(SONARR_URL, SONARR_API_KEY) if SONARR_URL and SONARR_API_KEY else None

# ---------- Plex: watchlist + bibliothèque ----------
def parse_guid_to_ids(guid: str):
    """
    Inputs like: 'tmdb://12345', 'tvdb://9876', 'imdb://tt123...', 'com.plexapp.agents.themoviedb://12345?lang=fr'
    Return dict: {"tmdb": "12345"} etc.
    """
    ids = {}
    if not guid:
        return ids
    # Normalize Plex agent style into scheme://id
    m = re.search(r'(tmdb|tvdb|imdb)[:/]+([a-z0-9]+)', guid, re.IGNORECASE)
    if m:
        ids[m.group(1).lower()] = m.group(2)
    return ids

def plex_existing_ids(plex: PlexServer):
    """
    Retourne les IDs connus (tmdb/tvdb/imdb) déjà présents dans Plex
    pour éviter de renvoyer des éléments déjà disponibles localement.
    """
    movie_ids = set()
    show_ids  = set()
    for section in plex.library.sections():
        try:
            if section.TYPE == "movie":
                for m in section.all():
                    for g in (getattr(m, "guids", []) or []):
                        ids = parse_guid_to_ids(str(g.id))
                        if "tmdb" in ids: movie_ids.add(("tmdb", ids["tmdb"]))
                        elif "imdb" in ids: movie_ids.add(("imdb", ids["imdb"]))
                        elif "tvdb" in ids: movie_ids.add(("tvdb", ids["tvdb"]))
            elif section.TYPE == "show":
                for s in section.all():
                    for g in (getattr(s, "guids", []) or []):
                        ids = parse_guid_to_ids(str(g.id))
                        if "tvdb" in ids: show_ids.add(("tvdb", ids["tvdb"]))
                        elif "tmdb" in ids: show_ids.add(("tmdb", ids["tmdb"]))
                        elif "imdb" in ids: show_ids.add(("imdb", ids["imdb"]))
        except Exception as e:
            v(f"[WARN] Section scan failed: {e}")
    return movie_ids, show_ids

def plex_watchlist_items():
    """
    Tente d'abord via MyPlexAccount.watchlist(), sinon fallback sur l’API Discover.
    Retourne deux listes: movies, shows. Chaque item: {"title", "type", "ids": {"tmdb": "...", ...}}
    """
    items_movies, items_shows = [], []

    # A) Méthode officielle via plexapi (compte)
    try:
        acct = MyPlexAccount(token=PLEX_TOKEN)
        # libtype: 'movie' / 'show'
        for libtype in ("movie", "show"):
            wl = acct.watchlist(libtype=libtype)  # peut lever selon versions
            for it in wl:
                ids = {}
                # it.guid ou it.guids
                try:
                    if getattr(it, "guids", None):
                        for g in it.guids:
                            ids.update(parse_guid_to_ids(str(g.id)))
                    elif getattr(it, "guid", None):
                        ids.update(parse_guid_to_ids(str(it.guid)))
                except Exception:
                    pass
                obj = {"title": getattr(it, "title", "<?>"), "type": libtype, "ids": ids}
                (items_movies if libtype == "movie" else items_shows).append(obj)
        return items_movies, items_shows
    except Exception as e:
        v(f"[INFO] watchlist via MyPlexAccount failed ({e}); trying Discover fallback…")

    # B) Fallback Discover API
    try:
        # NB: endpoints Discover évoluent; celui-ci marche souvent :
        # https://discover.provider.plex.tv/library/sections/watchlist/all
        url = "https://discover.provider.plex.tv/library/sections/watchlist/all"
        r = requests.get(url, headers={"X-Plex-Token": PLEX_TOKEN, "Accept":"application/json"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        for md in data.get("MediaContainer", {}).get("Metadata", []):
            typ = "movie" if md.get("type") == "movie" else ("show" if md.get("type") == "show" else None)
            if not typ: continue
            # GUIDs
            ids = {}
            for g in md.get("Guid", []):
                ids.update(parse_guid_to_ids(g.get("id","")))
            obj = {"title": md.get("title","<?>"), "type": typ, "ids": ids}
            (items_movies if typ=="movie" else items_shows).append(obj)
    except Exception as e:
        die(f"Impossible de récupérer la watchlist Plex (Discover): {e}")

    return items_movies, items_shows

# ---------- Radarr helpers ----------
def radarr_get_profiles():
    r = radarr.get(radarr.base_url + "/api/v3/qualityprofile", timeout=15)
    r.raise_for_status()
    return r.json()

def radarr_pick_profile_id(name_hint=""):
    profs = radarr_get_profiles()
    if name_hint:
        for p in profs:
            if p["name"].lower() == name_hint.lower():
                return p["id"]
    return profs[0]["id"] if profs else None

def radarr_existing_tmdb_ids():
    r = radarr.get(radarr.base_url + "/api/v3/movie", timeout=20)
    r.raise_for_status()
    ids = set()
    for m in r.json():
        tmdb = (m.get("tmdbId") or 0)
        if tmdb:
            ids.add(int(tmdb))
    return ids

def radarr_add_by_tmdb(tmdb_id: int, root: str, profile_id: int):
    # lookup first
    lr = radarr.get(radarr.base_url + "/api/v3/movie/lookup", params={"term": f"tmdb:{tmdb_id}"}, timeout=20)
    lr.raise_for_status()
    cand = next((x for x in lr.json() if int(x.get("tmdbId",0)) == tmdb_id), None)
    if not cand:
        return False, f"lookup miss tmdb:{tmdb_id}"
    payload = {
        "tmdbId": tmdb_id,
        "title": cand["title"],
        "qualityProfileId": profile_id,
        "titleSlug": cand["titleSlug"],
        "year": cand.get("year"),
        "monitored": True,
        "rootFolderPath": root,
        "addOptions": {"searchForMovie": True},
        "minimumAvailability": "released",
    }
    if DRY_RUN:
        v(f"[DRY] RADARR ADD: {payload}")
        return True, "dry_run"
    ar = radarr.post(radarr.base_url + "/api/v3/movie", json=payload, timeout=20)
    if ar.status_code in (200, 201):
        return True, "added"
    return False, f"radarr add failed ({ar.status_code}): {ar.text[:200]}"

# ---------- Sonarr helpers ----------
def sonarr_get_profiles():
    r = sonarr.get(sonarr.base_url + "/api/v3/qualityprofile", timeout=15)
    r.raise_for_status()
    return r.json()

def sonarr_pick_profile_id(name_hint=""):
    profs = sonarr_get_profiles()
    if name_hint:
        for p in profs:
            if p["name"].lower() == name_hint.lower():
                return p["id"]
    return profs[0]["id"] if profs else None

def sonarr_existing_series_ids():
    r = sonarr.get(sonarr.base_url + "/api/v3/series", timeout=25)
    r.raise_for_status()
    ids = {"tvdb": set(), "tmdb": set()}
    for s in r.json():
        if s.get("tvdbId"): ids["tvdb"].add(int(s["tvdbId"]))
        if s.get("tmdbId"): ids["tmdb"].add(int(s["tmdbId"]))
    return ids

def sonarr_add_by_id(ids: dict, root: str, profile_id: int):
    """
    Préférence TVDB, sinon TMDB. Déclenche le search.
    """
    tvdb = ids.get("tvdb")
    tmdb = ids.get("tmdb")
    term = f"tvdb:{tvdb}" if tvdb else (f"tmdb:{tmdb}" if tmdb else None)
    if not term:
        return False, "no usable id"

    lr = sonarr.get(sonarr.base_url + "/api/v3/series/lookup", params={"term": term}, timeout=25)
    lr.raise_for_status()
    results = lr.json()
    cand = None
    for x in results:
        if tvdb and int(x.get("tvdbId", 0)) == int(tvdb):
            cand = x; break
        if not tvdb and tmdb and int(x.get("tmdbId", 0)) == int(tmdb):
            cand = x; break
    if not cand:
        return False, f"lookup miss {term}"

    payload = {
        "title": cand["title"],
        "qualityProfileId": profile_id,
        "rootFolderPath": root,
        "titleSlug": cand["titleSlug"],
        "images": cand.get("images", []),
        "seasons": cand.get("seasons", []),
        "seasonFolder": True,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
        "tvdbId": cand.get("tvdbId"),
        "tmdbId": cand.get("tmdbId"),
    }
    if DRY_RUN:
        v(f"[DRY] SONARR ADD: {payload}")
        return True, "dry_run"
    ar = sonarr.post(sonarr.base_url + "/api/v3/series", json=payload, timeout=25)
    if ar.status_code in (200, 201):
        return True, "added"
    return False, f"sonarr add failed ({ar.status_code}): {ar.text[:200]}"

# ---------- MAIN ----------
def main():
    if not (PLEX_URL and PLEX_TOKEN):
        die("Configurer PLEX_URL/PLEX_TOKEN")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

    # Watchlist
    wl_movies, wl_shows = plex_watchlist_items()
    v(f"[INFO] Watchlist: {len(wl_movies)} films, {len(wl_shows)} séries")

    # Déjà dans Plex ?
    plex_movies, plex_shows = plex_existing_ids(plex)
    v(f"[INFO] IDs déjà dans Plex - films: {len(plex_movies)} / séries: {len(plex_shows)}")

    # --- RADARR ---
    if radarr:
        profile_id = radarr_pick_profile_id(RADARR_PROFILE)
        if not profile_id:
            die("Aucun quality profile Radarr")
        existing_tmdb = radarr_existing_tmdb_ids()
    else:
        v("[WARN] RADARR non configuré ou clé absente → films ignorés")
        existing_tmdb = set()

    # --- SONARR ---
    if sonarr:
        s_profile_id = sonarr_pick_profile_id(SONARR_PROFILE)
        if not s_profile_id:
            die("Aucun quality profile Sonarr")
        s_existing = sonarr_existing_series_ids()
    else:
        v("[WARN] SONARR non configuré ou clé absente → séries ignorées")
        s_existing = {"tvdb": set(), "tmdb": set()}

    added_movies = 0
    added_shows  = 0

    # Traiter FILMS
    for it in wl_movies:
        ids = it["ids"]
        title = it["title"]
        # skip si déjà dans Plex (tmdb prioritaire)
        key = None
        if "tmdb" in ids: key = ("tmdb", ids["tmdb"])
        elif "imdb" in ids: key = ("imdb", ids["imdb"])
        elif "tvdb" in ids: key = ("tvdb", ids["tvdb"])
        if key and key in plex_movies:
            v(f"[SKIP][Plex] Film déjà présent: {title} ({key[0]}:{key[1]})")
            continue

        if not radarr or "tmdb" not in ids:
            v(f"[SKIP] Film sans tmdbId ou Radarr absent: {title} {ids}")
            continue

        tmdb_id = int(re.sub(r"\D","", ids["tmdb"]))
        if tmdb_id in existing_tmdb:
            v(f"[SKIP][Radarr] Already in Radarr: {title} (tmdb:{tmdb_id})")
            continue

        ok, msg = radarr_add_by_tmdb(tmdb_id, RADARR_ROOT, profile_id)
        if ok:
            added_movies += 1
            log(f"[OK][Radarr] {title} (tmdb:{tmdb_id}) → {msg}")
        else:
            log(f"[FAIL][Radarr] {title} (tmdb:{tmdb_id}) → {msg}")

    # Traiter SÉRIES
    for it in wl_shows:
        ids = it["ids"]
        title = it["title"]
        # skip si déjà dans Plex
        key = None
        if "tvdb" in ids: key = ("tvdb", ids["tvdb"])
        elif "tmdb" in ids: key = ("tmdb", ids["tmdb"])
        elif "imdb" in ids: key = ("imdb", ids["imdb"])
        if key and key in plex_shows:
            v(f"[SKIP][Plex] Série déjà présente: {title} ({key[0]}:{key[1]})")
            continue

        if not sonarr:
            v(f"[SKIP] Sonarr absent: {title}")
            continue

        # éviter doublons Sonarr
        if "tvdb" in ids and ids["tvdb"].isdigit() and int(ids["tvdb"]) in s_existing["tvdb"]:
            v(f"[SKIP][Sonarr] Already in Sonarr (tvdb): {title}")
            continue
        if "tmdb" in ids and ids["tmdb"].isdigit() and int(ids["tmdb"]) in s_existing["tmdb"]:
            v(f"[SKIP][Sonarr] Already in Sonarr (tmdb): {title}")
            continue

        ok, msg = sonarr_add_by_id(ids, SONARR_ROOT, s_profile_id)
        if ok:
            added_shows += 1
            log(f"[OK][Sonarr] {title} {ids} → {msg}")
        else:
            log(f"[FAIL][Sonarr] {title} {ids} → {msg}")

    log(f"Done. Added: movies={added_movies}, shows={added_shows} (dry_run={DRY_RUN})")

if __name__ == "__main__":
    main()
