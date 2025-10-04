#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_plex_vs_folder.py

Compare les contenus (Films & Séries) présents dans Plex, Radarr/Sonarr et sur disque.

Sorties :
- Ajout d'une entrée "library_compare" dans MONITOR_LOG_FILE (défaut: /mnt/data/system_monitor_log.json)
- Affichage console (résumé)
- (Optionnel) webhook Discord via DISCORD_WEBHOOK

ENV attendus (exemples) :
  PLEX_SERVER=http://192.168.3.39:32400
  PLEX_TOKEN=xxxxxxxxxxxx
  RADARR_URL=http://radarr:7878
  RADARR_API_KEY=xxxxxxxx
  SONARR_URL=http://sonarr:8989
  SONARR_API_KEY=xxxxxxxx
  MOVIE_DIRS=/mnt/media/films:/mnt/media/films_2
  TV_DIRS=/mnt/media/series:/mnt/media/series_2
  PATH_MAP=/data=/mnt/media|/downloads=/mnt/downloads
  RADARR_ON_DISK_ONLY=1
  SONARR_ON_DISK_ONLY=1
  DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
  MONITOR_LOG_FILE=/mnt/data/system_monitor_log.json

Notes :
- Sections Plex détectées automatiquement par type ('movie' et 'show'), noms FR/EN gérés.
- Normalisation des titres (accents, années, ponctuation légère) pour limiter les faux positifs.
- Validation par chemins réels Plex (détection de “fantômes” si les fichiers/répertoires n’existent pas côté conteneur).
"""

import os, re, json, time, urllib.request, unicodedata
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

PLEX_URL = os.getenv("PLEX_SERVER", "").strip().rstrip("/")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "").strip()
RADARR_URL = os.getenv("RADARR_URL", "").strip().rstrip("/")
RADARR_KEY = os.getenv("RADARR_API_KEY", "").strip()
SONARR_URL = os.getenv("SONARR_URL", "").strip().rstrip("/")
SONARR_KEY = os.getenv("SONARR_API_KEY", "").strip()

MOVIE_DIRS = [p for p in os.getenv("MOVIE_DIRS", "/mnt/media/films").split(":") if p]
TV_DIRS = [p for p in os.getenv("TV_DIRS", "/mnt/media/series").split(":") if p]

TIMEOUT = 12  # requêtes HTTP Radarr/Sonarr
MAX_ITEMS_DISCORD = 20  # limite items listés dans Discord pour éviter le spam


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


# -------- Helpers titres ----------
def _fold_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    )


def _norm_title(s: str) -> str:
    s = _fold_accents(s).lower()
    s = re.sub(r"[\(\[\{]\s*\d{4}\s*[\)\]\}]", "", s)  # retire "(2020)" etc.
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"[^\w\s\-:&']", " ", s)
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


# -------- Helpers PATH MAP ----------
def _parse_path_map(envval: str) -> list[tuple[str, str]]:
    """
    PATH_MAP='/data=/mnt/media|/downloads=/mnt/downloads'
    """
    maps = []
    if not envval:
        return maps
    for pair in envval.split("|"):
        if "=" in pair:
            src, dst = pair.split("=", 1)
            src, dst = src.strip(), dst.strip()
            if src and dst:
                maps.append((src, dst))
    # appliquer les plus spécifiques d'abord
    maps.sort(key=lambda x: len(x[0]), reverse=True)
    return maps


PATH_MAP = _parse_path_map(os.getenv("PATH_MAP", ""))


def _translate_path(p: str) -> str:
    if not p:
        return p
    for src, dst in PATH_MAP:
        if p.startswith(src.rstrip("/") + "/") or p == src:
            return p.replace(src, dst, 1)
    return p


def _safe_exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


# -------- Log JSON avec fallback ----------
def _append_json_log(entry: Dict):
    entry["timestamp"] = datetime.now().isoformat()
    target = Path(LOG_JSON)

    def _write(p: Path, data):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # charge existant
    data = []
    if target.exists():
        try:
            cur = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(cur, list):
                data = cur
        except Exception:
            data = []

    data.append(entry)

    # tentative 1: chemin configuré (peut être /mnt/data/…)
    try:
        _write(target, data)
        return
    except PermissionError:
        pass
    except Exception:
        pass

    # fallback: ~/.cache/robert2/system_monitor_log.json
    fallback = Path.home() / ".cache/robert2/system_monitor_log.json"
    try:
        if fallback.exists():
            try:
                cur = json.loads(fallback.read_text(encoding="utf-8"))
                if isinstance(cur, list):
                    data = cur + [entry]
            except Exception:
                pass
        _write(fallback, data)
        print(f"[WARN] Permission refusée sur {target}. Écrit dans {fallback}.")
    except Exception as e:
        print(f"[ERROR] Impossible d’écrire un log JSON (même en fallback): {e}")


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
    only_on_disk = os.getenv("RADARR_ON_DISK_ONLY", "0") == "1"
    if not RADARR_URL or not RADARR_KEY:
        return set()
    ok, res = _http_get_json(f"{RADARR_URL}/api/v3/movie", {"X-Api-Key": RADARR_KEY})
    if not ok or not isinstance(res, list):
        return set()
    titles = set()
    for m in res:
        t = (m.get("title") or "").strip()
        if not t:
            continue
        if only_on_disk:
            # Radarr considère "sur disque" si movieFile est présent
            if m.get("movieFile"):
                titles.add(t)
        else:
            titles.add(t)
    return titles


def _sonarr_titles() -> Set[str]:
    only_on_disk = os.getenv("SONARR_ON_DISK_ONLY", "0") == "1"
    if not SONARR_URL or not SONARR_KEY:
        return set()
    ok, res = _http_get_json(f"{SONARR_URL}/api/v3/series", {"X-Api-Key": SONARR_KEY})
    if not ok or not isinstance(res, list):
        return set()
    titles = set()
    for s in res:
        t = (s.get("title") or "").strip()
        if not t:
            continue
        if only_on_disk:
            stats = s.get("statistics") or {}
            if int(stats.get("episodeFileCount", 0)) > 0:
                titles.add(t)
        else:
            titles.add(t)
    return titles


# -------- Plex (titres + chemins réels) ----------
def _plex_titles() -> Tuple[Set[str], Set[str], list, Set[str], Set[str]]:
    """
    Retourne: (titles_movies, titles_shows, debug, plex_paths_movies, plex_paths_shows)
    plex_paths_* = ensembles de dossiers/fichiers vus par Plex (traduit via PATH_MAP)
    """
    movies: Set[str] = set()
    shows: Set[str] = set()
    debug = []
    plex_paths_movies: Set[str] = set()
    plex_paths_shows: Set[str] = set()

    if not PLEX_URL or not PLEX_TOKEN:
        debug.append("Plex URL/token manquants.")
        return movies, shows, debug, plex_paths_movies, plex_paths_shows
    try:
        from plexapi.server import PlexServer

        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        for sec in plex.library.sections():
            stype = getattr(sec, "type", None)
            sname = getattr(sec, "title", "?")
            try:
                items = sec.all()
            except Exception as e:
                debug.append(f"Erreur section {sname}: {e}")
                continue

            if stype == "movie":
                for m in items:
                    t = getattr(m, "title", None)
                    if t:
                        movies.add(t)
                    # collecter les chemins pour valider l'existence
                    try:
                        for media in m.media:
                            for part in media.parts:
                                p = _translate_path(part.file)
                                plex_paths_movies.add(os.path.dirname(p))
                    except Exception:
                        pass
                debug.append(f"Plex section '{sname}'(movie): {len(items)} éléments.")
            elif stype == "show":
                for s in items:
                    t = getattr(s, "title", None)
                    if t:
                        shows.add(t)
                    try:
                        for ep in s.episodes():
                            for media in ep.media:
                                for part in media.parts:
                                    p = _translate_path(part.file)
                                    plex_paths_shows.add(os.path.dirname(p))
                    except Exception:
                        pass
                debug.append(f"Plex section '{sname}'(show): {len(items)} éléments.")
    except Exception as e:
        debug.append(f"Echec connexion Plex: {e}")
    return movies, shows, debug, plex_paths_movies, plex_paths_shows


# -------- Main compare ----------
def compare():
    # Dossiers (tels que vus par le CONTENEUR)
    disk_movies_raw = _list_dirs(MOVIE_DIRS)
    disk_shows_raw = _list_dirs(TV_DIRS)

    # Normalisés (par titre)
    disk_movies = {_norm_title(x) for x in disk_movies_raw}
    disk_shows = {_norm_title(x) for x in disk_shows_raw}

    # Plex (titres + chemins réels)
    plex_movies_raw, plex_shows_raw, plex_dbg, plex_paths_movies, plex_paths_shows = (
        _plex_titles()
    )

    plex_movies = {_norm_title(x) for x in plex_movies_raw}
    plex_shows = {_norm_title(x) for x in plex_shows_raw}

    # chemins réels existants côté conteneur (après PATH_MAP)
    plex_movies_missing = {p for p in plex_paths_movies if not _safe_exists(p)}
    plex_shows_missing = {p for p in plex_paths_shows if not _safe_exists(p)}

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
            "plex_missing_paths_count": len(plex_movies_missing),
            "plex_missing_paths_samples": sorted(list(plex_movies_missing))[:20],
        },
        "shows": {
            "ok_everywhere_count": len(shows_ok_everywhere),
            "only_disk": sorted(list(shows_only_disk)),
            "only_plex": sorted(list(shows_only_plex)),
            "only_sonarr": sorted(list(shows_only_sonarr)),
            "plex_missing_paths_count": len(plex_shows_missing),
            "plex_missing_paths_samples": sorted(list(plex_shows_missing))[:20],
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
            "path_map": PATH_MAP,
            "ts": int(time.time()),
        },
    }
    return result


def main():
    res = compare()

    # Console - résumé
    print("=== FILMS (résumé) ===")
    print(f"- OK partout: {res['movies']['ok_everywhere_count']}")
    print(f"- Disque uniquement: {len(res['movies']['only_disk'])}")
    print(f"- Plex uniquement: {len(res['movies']['only_plex'])}")
    print(f"- Radarr uniquement: {len(res['movies']['only_radarr'])}")
    print(f"- Plex chemins manquants: {res['movies']['plex_missing_paths_count']}")

    print("\n=== SÉRIES (résumé) ===")
    print(f"- OK partout: {res['shows']['ok_everywhere_count']}")
    print(f"- Disque uniquement: {len(res['shows']['only_disk'])}")
    print(f"- Plex uniquement: {len(res['shows']['only_plex'])}")
    print(f"- Sonarr uniquement: {len(res['shows']['only_sonarr'])}")
    print(f"- Plex chemins manquants: {res['shows']['plex_missing_paths_count']}")

    # Append dans le JSON global de monitoring
    entry = {"library_compare": res}
    _append_json_log(entry)

    # Discord (optionnel, avec extraits)
    if DISCORD_WEBHOOK:
        lines = []
        lines.append("📊 **Comparaison Librairie**")
        lines.append(
            f"🎬 Films — OK:{res['movies']['ok_everywhere_count']} "
            f"| Disk:{len(res['movies']['only_disk'])} "
            f"| Plex:{len(res['movies']['only_plex'])} "
            f"| Radarr:{len(res['movies']['only_radarr'])} "
            f"| Chemins manquants:{res['movies']['plex_missing_paths_count']}"
        )
        lines.append(
            f"📺 Séries — OK:{res['shows']['ok_everywhere_count']} "
            f"| Disk:{len(res['shows']['only_disk'])} "
            f"| Plex:{len(res['shows']['only_plex'])} "
            f"| Sonarr:{len(res['shows']['only_sonarr'])} "
            f"| Chemins manquants:{res['shows']['plex_missing_paths_count']}"
        )

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

        # Quelques chemins manquants côté Plex (aide au diag)
        m_miss = res["movies"]["plex_missing_paths_samples"]
        s_miss = res["shows"]["plex_missing_paths_samples"]
        if m_miss:
            lines.append(excerpt("Chemins films Plex introuvables", m_miss))
        if s_miss:
            lines.append(excerpt("Chemins séries Plex introuvables", s_miss))

        for x in (m_od, m_op, m_or, s_od, s_op, s_os):
            if x:
                lines.append(x)

        _discord_send("\n".join([l for l in lines if l]))


if __name__ == "__main__":
    main()
