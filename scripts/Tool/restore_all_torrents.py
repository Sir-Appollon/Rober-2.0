#!/usr/bin/env python3
import os
import time
from deluge_client import DelugeRPCClient

# Connexion à Deluge
client = DelugeRPCClient("127.0.0.1", 58846, "localclient", os.getenv("DELUGE_PASSWORD"))
client.connect()

# Dossier avec tous les .torrent
torrent_dir = "/home/paul/homelab/media_serveur/Rober-2.0/config/deluge/state"
download_dir = "/downloads"  # Monté dans le container Deluge

count = 0
for filename in os.listdir(torrent_dir):
    if filename.endswith(".torrent"):
        filepath = os.path.join(torrent_dir, filename)
        with open(filepath, "rb") as f:
            torrent_data = f.read()
        try:
            client.call(
                "core.add_torrent_file",
                filename,
                torrent_data,
                {"download_location": download_dir}
            )
            print(f"✅ Ajouté : {filename}")
            count += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"❌ Erreur avec {filename} : {e}")

print(f"\n🧾 {count} torrents réimportés.")
