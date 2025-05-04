from deluge_client import DelugeRPCClient

try:
    with DelugeRPCClient("127.0.0.1", 58846, "paul", "deluge") as client:
        print("Connection to Deluge succeeded.")
        torrents = client.call("core.get_torrents_status", {}, ["name"])

        # Call the core.get_external_ip method
        external_ip = client.call("core.get_external_ip")
        print(f"External IP: {external_ip}")

except Exception as e:
    print("Connection to Deluge failed:")
    print(e)
