#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_plex_vs_folder.py
Compare les contenus (Films & Séries) présents dans Plex, Radarr/Sonarr et sur disque.

Sorties :
- Ajout d'une entrée "library_compare" dans /mnt/data/system_monitor_log.json
- Affichage console
- (Optionnel) webhook Discord via DISCORD_WEBHOOK

ENV attendus (exemples) :
  PLEX_SERVER=http://192.168.3.39:32400
  PLEX_TOKEN=xxxxxxxxxxxx
  RADARR_URL=http://localhost:7878
  RADARR_API_KEY=xxxxxxxx
  SONARR_URL=http://localhost:8989
  SONARR_API_KEY=xxxxxxxx
  MOVIE_DIRS=/mnt/media/films:/mnt/media/films_2
  TV_DIRS=/mnt/media/series:/mnt/media/series_2
  DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

Notes :
- Sections Plex détectées automatiquement par type ('movie' et 'show'), noms FR/EN gérés.
- Normalisation des titres pour limiter les faux positifs (retire année, ponctuation légère, casse).
"""

import os, re, json, time, urllib.request
from pathlib import Path
from datetime import datetime
from typing import Iterable, Set, Dict, Tuple


# -------- .env (simple) ----------
def _load_dotenv_simple(path: str):
    p = Path(path)
    if not p.is_file():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Essaye /app/.env puis ROOT/.env
_load_dotenv_simple("/app/.env")
if "ROOT" in os.environ:
    _load_dotenv_simple(os.path.join(os.environ["ROOT"], ".env"))

# -------- Config ----------
LOG_JSON = os.environ.get("MONITOR_LOG_FILE", "/mnt/data/system_monitor_log.json")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()

PLEX_URL = os.getenv("PLEX_SERVER", "").strip()
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "").strip()
RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.getenv("RADARR_API_KEY", "").strip()
SONARR_URL = os.getenv("SONARR_URL", "").rstrip("/")
SONARR_KEY = os.getenv("SONARR_API_KEY", "").strip()

MOVIE_DIRS = [p for p in os.getenv("MOVIE_DIRS", "/mnt/media/films").split(":") if p]
TV_DIRS = [p for p in os.getenv("TV_DIRS", "/mnt/media/series").split(":") if p]

TIMEOUT = 12  # requêtes HTTP Radarr/Sonarr
MAX_ITEMS_DISCORD = 20  # limite items listés dans Discord pour ne pas spammer


# -------- Discord ----------
def _discord_send(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg[:1900]}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        pass


# -------- Helpers ----------
def _norm_title(s: str) -> str:
    """Normalise un titre pour la comparaison (casse, année entre parenthèses, ponctuation simple)."""
    s = s or ""
    s = s.strip().lower()
    # retire année "(2020)" ou "[2020]" en fin ou quasi-fin
    s = re.sub(r"[\(\[\{]\s*\d{4}\s*[\)\]\}]", "", s)
    # remplace . _ par espaces
    s = re.sub(r"[._]+", " ", s)
    # retire ponctuation légère
    s = re.sub(r"[^\w\s\-:&']", " ", s)
    # espaces multiples -> un
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _list_dirs(paths: Iterable[str]) -> Set[str]:
    names: Set[str] = set()
    for base in paths:
        p = Path(base)
        if not p.exists() or not p.is_dir():
            continue
        for child in p.iterdir():
            if child.is_dir():
                names.add(child.name)
    return names


def _append_json_log(entry: Dict):
    entry["timestamp"] = datetime.now().isoformat()
    p = Path(LOG_JSON)
    if not p.exists():
        p.write_text(json.dumps([entry], indent=2), encoding="utf-8")
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    data.append(entry)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -------- Radarr / Sonarr ----------
def _http_get_json(url: str, headers: Dict[str, str]) -> Tuple[bool, object]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
        return True, json.loads(body.decode("utf-8"))
    except Exception as e:
        return False, str(e)


def _radarr_titles() -> Set[str]:
    if not RADARR_URL or not RADARR_KEY:
        return set()
    ok, res = _http_get_json(f"{RADARR_URL}/api/v3/movie", {"X-Api-Key": RADARR_KEY})
    if not ok or not isinstance(res, list):
        return set()
    titles = set()
    for m in res:
        t = (m.get("title") or "").strip()
        if t:
            titles.add(t)
    return titles


def _sonarr_titles() -> Set[str]:
    if not SONARR_URL or not SONARR_KEY:
        return set()
    ok, res = _http_get_json(f"{SONARR_URL}/api/v3/series", {"X-Api-Key": SONARR_KEY})
    if not ok or not isinstance(res, list):
        return set()
    titles = set()
    for s in res:
        t = (s.get("title") or "").strip()
        if t:
            titles.add(t)
    return titles


# -------- Plex ----------
def _plex_titles() -> Tuple[Set[str], Set[str], list]:
    movies: Set[str] = set()
    shows: Set[str] = set()
    debug = []
    if not PLEX_URL or not PLEX_TOKEN:
        debug.append("Plex URL/token manquants.")
        return movies, shows, debug
    try:
        from plexapi.server import PlexServer

        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        for sec in plex.library.sections():
            try:
                stype = getattr(sec, "type", None)
                sname = getattr(sec, "title", "?")
                if stype == "movie":
                    for m in sec.all():
                        if getattr(m, "title", None):
                            movies.add(m.title)
                    debug.append(
                        f"Plex section '{sname}'(movie): {len(sec.all())} éléments."
                    )
                elif stype == "show":
                    for s in sec.all():
                        if getattr(s, "title", None):
                            shows.add(s.title)
                    debug.append(
                        f"Plex section '{sname}'(show): {len(sec.all())} éléments."
                    )
            except Exception as e:
                debug.append(f"Erreur section Plex: {e}")
    except Exception as e:
        debug.append(f"Echec connexion Plex: {e}")
    return movies, shows, debug


# -------- Main compare ----------
def compare():
    # Dossiers
    disk_movies_raw = _list_dirs(MOVIE_DIRS)
    disk_shows_raw = _list_dirs(TV_DIRS)

    # Normalisés
    disk_movies = {_norm_title(x) for x in disk_movies_raw}
    disk_shows = {_norm_title(x) for x in disk_shows_raw}

    # Plex
    plex_movies_raw, plex_shows_raw, plex_dbg = _plex_titles()
    plex_movies = {_norm_title(x) for x in plex_movies_raw}
    plex_shows = {_norm_title(x) for x in plex_shows_raw}

    # Radarr / Sonarr
    radarr_movies_raw = _radarr_titles()
    sonarr_shows_raw = _sonarr_titles()
    radarr_movies = {_norm_title(x) for x in radarr_movies_raw}
    sonarr_shows = {_norm_title(x) for x in sonarr_shows_raw}

    # --- FILMS ---
    movies_ok_everywhere = disk_movies & plex_movies & radarr_movies
    movies_only_disk = disk_movies - plex_movies - radarr_movies
    movies_only_plex = plex_movies - disk_movies
    movies_only_radarr = radarr_movies - disk_movies

    # --- SERIES ---
    shows_ok_everywhere = disk_shows & plex_shows & sonarr_shows
    shows_only_disk = disk_shows - plex_shows - sonarr_shows
    shows_only_plex = plex_shows - disk_shows
    shows_only_sonarr = sonarr_shows - disk_shows

    result = {
        "movies": {
            "ok_everywhere_count": len(movies_ok_everywhere),
            "only_disk": sorted(list(movies_only_disk)),
            "only_plex": sorted(list(movies_only_plex)),
            "only_radarr": sorted(list(movies_only_radarr)),
        },
        "shows": {
            "ok_everywhere_count": len(shows_ok_everywhere),
            "only_disk": sorted(list(shows_only_disk)),
            "only_plex": sorted(list(shows_only_plex)),
            "only_sonarr": sorted(list(shows_only_sonarr)),
        },
        "meta": {
            "disk_movies_count": len(disk_movies),
            "disk_shows_count": len(disk_shows),
            "plex_movies_count": len(plex_movies),
            "plex_shows_count": len(plex_shows),
            "radarr_movies_count": len(radarr_movies),
            "sonarr_shows_count": len(sonarr_shows),
            "dirs_movies_scanned": MOVIE_DIRS,
            "dirs_tv_scanned": TV_DIRS,
            "plex_debug": plex_dbg,
            "ts": int(time.time()),
        },
    }
    return result


def main():
    res = compare()

    # Console
    print("=== FILMS (résumé) ===")
    print(f"- OK partout: {res['movies']['ok_everywhere_count']}")
    print(f"- Disque uniquement: {len(res['movies']['only_disk'])}")
    print(f"- Plex uniquement: {len(res['movies']['only_plex'])}")
    print(f"- Radarr uniquement: {len(res['movies']['only_radarr'])}")

    print("\n=== SÉRIES (résumé) ===")
    print(f"- OK partout: {res['shows']['ok_everywhere_count']}")
    print(f"- Disque uniquement: {len(res['shows']['only_disk'])}")
    print(f"- Plex uniquement: {len(res['shows']['only_plex'])}")
    print(f"- Sonarr uniquement: {len(res['shows']['only_sonarr'])}")

    # Append dans le JSON global de monitoring
    entry = {"library_compare": res}
    _append_json_log(entry)

    # Discord (optionnel, avec petits extraits)
    if DISCORD_WEBHOOK:
        lines = []
        lines.append("📊 **Comparaison Librairie**")
        lines.append(
            f"🎬 Films — OK: {res['movies']['ok_everywhere_count']} | Disk:{len(res['movies']['only_disk'])} | Plex:{len(res['movies']['only_plex'])} | Radarr:{len(res['movies']['only_radarr'])}"
        )
        lines.append(
            f"📺 Séries — OK: {res['shows']['ok_everywhere_count']} | Disk:{len(res['shows']['only_disk'])} | Plex:{len(res['shows']['only_plex'])} | Sonarr:{len(res['shows']['only_sonarr'])}"
        )

        # Extraits limités
        def excerpt(title, items):
            if not items:
                return None
            shown = items[:MAX_ITEMS_DISCORD]
            extra = (
                ""
                if len(items) <= MAX_ITEMS_DISCORD
                else f" …(+{len(items)-MAX_ITEMS_DISCORD})"
            )
            return f"• {title}: " + ", ".join(f"`{i}`" for i in shown) + extra

        m_od = excerpt("Films disque uniquement", res["movies"]["only_disk"])
        m_op = excerpt("Films Plex uniquement", res["movies"]["only_plex"])
        m_or = excerpt("Films Radarr uniquement", res["movies"]["only_radarr"])
        s_od = excerpt("Séries disque uniquement", res["shows"]["only_disk"])
        s_op = excerpt("Séries Plex uniquement", res["shows"]["only_plex"])
        s_os = excerpt("Séries Sonarr uniquement", res["shows"]["only_sonarr"])

        for x in (m_od, m_op, m_or, s_od, s_op, s_os):
            if x:
                lines.append(x)

        _discord_send("\n".join(lines))


if __name__ == "__main__":
    main()
