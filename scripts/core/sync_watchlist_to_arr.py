#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pulsarr_export_watchlists.py
- Fetch all Pulsarr users (you + friends) and export their watchlists.
- Auth: X-API-Key header.
- Env:
    PULSARR_URL        e.g. http://pulsarr:8080  (no trailing slash)
    PULSARR_API_KEY    your Pulsarr API key
    OUT_DIR            optional, default=/mnt/data
- CLI (optional filters):
    --only USERNAME            (exact or case-insensitive contains)
    --type {movie,show,all}    filter itemKind
    --format {csv,json,md}     default=csv (also always writes a full JSON dump)
"""

import os, sys, re, json, csv, argparse
from datetime import datetime
from pathlib import Path

import requests

def env(name, default=None):
    v = os.getenv(name, default)
    if v is None or (isinstance(v,str) and not v.strip()):
        return None
    return v.strip()

def norm_base(url):
    return re.sub(r"/+$", "", url or "")

def get(session, base, path):
    url = f"{base}{path}"
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def pick(lst, *keys):
    return {k: lst.get(k) for k in keys}

def slug(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "unknown"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Filter username (exact or contains, case-insensitive)")
    ap.add_argument("--type", choices=["movie","show","all"], default="all", help="Filter item kind")
    ap.add_argument("--format", choices=["csv","json","md"], default="csv")
    args = ap.parse_args()

    base = norm_base(env("PULSARR_URL"))
    api_key = env("PULSARR_API_KEY")
    out_dir = Path(env("OUT_DIR", "/mnt/data")).resolve()

    if not base or not api_key:
        print("❌ Missing PULSARR_URL or PULSARR_API_KEY in environment.", file=sys.stderr)
        sys.exit(2)

    out_dir.mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    sess.headers.update({"X-API-Key": api_key, "Accept": "application/json"})

    # 1) List users (with watchlist counts)
    #    GET /v1/users/users/list/with-counts
    users = get(sess, base, "/v1/users/users/list/with-counts")

    # Optional filter by name
    wanted_users = []
    if args.only:
        needle = args.only.lower()
        for u in users:
            name = (u.get("name") or u.get("username") or "").lower()
            if name == needle or needle in name:
                wanted_users.append(u)
        if not wanted_users:
            print(f"⚠️ No match for --only={args.only}. Exiting.")
            sys.exit(0)
    else:
        wanted_users = users

    # 2) For each user, fetch watchlist items
    #    GET /v1/users/:userId/watchlist
    all_rows = []
    raw_dump = {"generated_at": datetime.utcnow().isoformat()+"Z", "users": []}
    for u in wanted_users:
        uid   = u.get("id")
        uname = u.get("name") or u.get("username") or f"user_{uid}"
        try:
            items = get(sess, base, f"/v1/users/{uid}/watchlist")
        except requests.HTTPError as e:
            print(f"❌ Failed fetching watchlist for {uname} (id={uid}): {e}", file=sys.stderr)
            continue

        # normalize and filter
        filtered = []
        for it in items or []:
            kind = (it.get("itemKind") or it.get("kind") or "").lower()  # 'movie' or 'show'
            if args.type != "all" and kind != args.type:
                continue
            row = {
                "user_id": uid,
                "user_name": uname,
                "item_id": it.get("id") or it.get("tmdbId") or it.get("imdbId") or "",
                "item_kind": kind,
                "title": it.get("title") or "",
                "year": it.get("year") or "",
                "tmdb_id": it.get("tmdbId") or "",
                "imdb_id": it.get("imdbId") or "",
                "tvdb_id": it.get("tvdbId") or "",
                "plex_guid": it.get("plexGuid") or "",
                "added_at": it.get("addedAt") or it.get("createdAt") or "",
                "source": it.get("source") or "",       # e.g., 'plex'
                "notes": it.get("notes") or "",
            }
            filtered.append(row)
            all_rows.append(row)

        raw_dump["users"].append({
            "id": uid,
            "name": uname,
            "counts": pick(u, "movieCount","showCount"),
            "items": filtered
        })
        print(f"• {uname}: {len(filtered)} items")

    # 3) Write outputs
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"pulsarr_watchlists_{ts}"
    # Always dump full JSON (easy to parse later)
    json_path = out_dir / f"{base_name}.full.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(raw_dump, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON  → {json_path}")

    if args.format == "json":
        # also a compact summary JSON (flat rows)
        flat_path = out_dir / f"{base_name}.rows.json"
        with flat_path.open("w", encoding="utf-8") as f:
            json.dump(all_rows, f, indent=2, ensure_ascii=False)
        print(f"✅ JSON  → {flat_path}")

    elif args.format == "csv":
        csv_path = out_dir / f"{base_name}.csv"
        cols = ["user_id","user_name","item_kind","title","year","tmdb_id","imdb_id","tvdb_id","plex_guid","added_at","source","notes","item_id"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in all_rows:
                w.writerow(r)
        print(f"✅ CSV   → {csv_path}")

    elif args.format == "md":
        md_path = out_dir / f"{base_name}.md"
        with md_path.open("w", encoding="utf-8") as f:
            f.write(f"# Pulsarr Watchlists ({ts})\n\n")
            f.write("| User | Kind | Title | Year | TMDB | IMDB |\n|---|---|---|---|---|---|\n")
            for r in all_rows:
                tmdb = f"[{r['tmdb_id']}](https://www.themoviedb.org/{'movie' if r['item_kind']=='movie' else 'tv'}/{r['tmdb_id']})" if r.get("tmdb_id") else ""
                imdb = f"[{r['imdb_id']}](https://www.imdb.com/title/{r['imdb_id']}/)" if r.get("imdb_id") else ""
                title = (r["title"] or "").replace("|","¦")
                f.write(f"| {r['user_name']} | {r['item_kind']} | {title} | {r.get('year','')} | {tmdb} | {imdb} |\n")
        print(f"✅ Markdown → {md_path}")

    # Exit code for CI/automation convenience
    print(f"Done. Total items: {len(all_rows)}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr); sys.exit(1)
