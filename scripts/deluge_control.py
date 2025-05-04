from deluge_client import DelugeRPCClient

try:
    with DelugeRPCClient("127.0.0.1", 58846, "paul", "deluge") as client:
        print("Connection to Deluge succeeded.")
        torrents = client.call("core.get_torrents_status", {}, ["name"])

        # Ask for session-level info (network, speed, etc.)
        status = client.call(
            "core.get_session_status", ["external_ip", "download_rate", "upload_rate"]
        )

        print("Network info:")
        print(f"  External IP: {status.get('external_ip')}")
        print(f"  Download rate: {status.get('download_rate')} B/s")
        print(f"  Upload rate: {status.get('upload_rate')} B/s")

        # Dump all available fields
        status = client.call("core.get_session_status", [])
        print("🧩 All session status fields:")
        for key, value in status.items():
            print(f"  {key}: {value}")

except Exception as e:
    print("Connection to Deluge failed:")
    print(e)
