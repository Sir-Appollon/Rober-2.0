from deluge_client import DelugeRPCClient

with DelugeRPCClient("127.0.0.1", 58846, "localclient", "deluge") as client:
    torrents = client.call("core.get_torrents_status", {}, ["name"])
    print(torrents)
