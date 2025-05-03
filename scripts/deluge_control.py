from deluge_client import DelugeRPCClient

try:
    with DelugeRPCClient("127.0.0.1", 58846, "localclient", "deluge") as client:
        print("✅ Connection to Deluge succeeded.")
        torrents = client.call("core.get_torrents_status", {}, ["name"])
        print("📦 Torrents:")
        for torrent_id, info in torrents.items():
            print(f"- {torrent_id} → {info['name']}")
except Exception as e:
    print("❌ Connection to Deluge failed:")
    print(e)
