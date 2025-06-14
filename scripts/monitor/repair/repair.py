import json
import subprocess
import os
import re
import importlib.util
import requests
from dotenv import load_dotenv

ALERT_STATE_FILE = "/mnt/data/alert_state.json"
CONFIG_PATH = "/app/config/deluge/core.conf"
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
load_dotenv(dotenv_path)

send_discord_message = None


def setup_discord():
    global send_discord_message
    discord_paths = [
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "discord", "discord_notify.py")
        ),
        os.path.abspath(
            os.path.join(
                os.path.dirname(__file__), "..", "discord", "discord_notify.py"
            )
        ),
    ]
    for discord_path in discord_paths:
        if os.path.isfile(discord_path):
            try:
                spec = importlib.util.spec_from_file_location(
                    "discord_notify", discord_path
                )
                discord_notify = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(discord_notify)
                send_discord_message = discord_notify.send_discord_message
                break
            except Exception:
                pass


def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def get_vpn_internal_ip():
    print("[INFO] Retrieving internal VPN IP (tun0)...")
    try:
        result = subprocess.run(
            ["docker", "exec", "vpn", "ip", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
        )
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            ip = match.group(1)
            print(f"[VPN] Local VPN IP detected: {ip}")
            return ip
        else:
            raise RuntimeError("No IP detected on interface tun0")
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed to detect internal VPN IP: {e}")


def extract_interface_ips_from_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()
            listen = re.search(r'"listen_interface"\s*:\s*"([^"]+)"', content)
            outgoing = re.search(r'"outgoing_interface"\s*:\s*"([^"]+)"', content)
            return {
                "listen_interface": listen.group(1) if listen else None,
                "outgoing_interface": outgoing.group(1) if outgoing else None,
            }
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed to read core.conf: {e}")


def verify_interface_consistency():
    vpn_ip = get_vpn_internal_ip()
    config_ips = extract_interface_ips_from_config()

    print(f"[DEBUG] VPN IP = {vpn_ip}")
    print(f"[DEBUG] core.conf listen_interface = {config_ips['listen_interface']}")
    print(f"[DEBUG] core.conf outgoing_interface = {config_ips['outgoing_interface']}")

    return (
        config_ips["listen_interface"] == vpn_ip
        and config_ips["outgoing_interface"] == vpn_ip,
        vpn_ip,
        config_ips,
    )


def launch_repair_deluge_ip():
    print("[ACTION] Launching Deluge repair procedure...")
    subprocess.run(["python3", "/app/repair/ip_adress_up.py"])


def handle_deluge_verification():
    state = load_alert_state()
    if state.get("deluge_status") != "inactive":
        return

    print("[INFO] Deluge was marked as inactive in previous state.")
    if send_discord_message:
        send_discord_message(
            "[ALERT - test] Deluge appears inactive: validating the issue."
        )

    try:
        consistent, vpn_ip, config_ips = verify_interface_consistency()

        if not consistent:
            print("[CONFIRMED] Inconsistent IP: triggering repair.")
            if send_discord_message:
                send_discord_message(
                    "[ALERT - confirmation] Deluge is inactive: mismatched IP address."
                )
            launch_repair_deluge_ip()
            if send_discord_message:
                send_discord_message(
                    f"[ALERT - repair complete] IP address updated: {vpn_ip}"
                )
        else:
            print("[INFO] IPs are consistent, no repair needed.")
    except Exception as e:
        print(f"[ERROR] Secondary verification failed: {e}")
        if send_discord_message:
            send_discord_message(f"[ERROR] Verification failed: {str(e)}")

def check_plex_external_status():
    domain = os.getenv("DOMAIN")
    plex_token = os.getenv("PLEX_TOKEN")

    if not domain or not plex_token:
        print("[ERROR] DOMAIN or PLEX_TOKEN not set in environment.")
        return

    url = f"{domain.rstrip('/')}/status/sessions"
    headers = {"X-Plex-Token": plex_token}

    try:
        response = requests.get(url, headers=headers, timeout=5)

        if response.status_code == 200:
            print("[INFO] Plex external access is online.")
        elif response.status_code in [301, 302, 401]:
            print(f"[INFO] Plex might be online (status: {response.status_code}), possible redirect or unauthorized.")
            if send_discord_message:
                send_discord_message("[INFO] Plex external responded, probably online. Possible false error (redirect or auth).")
        else:
            print(f"[ALERT] Plex external returned status code {response.status_code}")
            if send_discord_message:
                send_discord_message(f"[ALERT] Plex external access appears to be offline (status code {response.status_code}).")
    except Exception as e:
        print(f"[ERROR] Plex external check failed: {e}")
        if send_discord_message:
            send_discord_message("[ALERT] Plex external access is offline (exception during check).")


def main():
    print("[DEBUG] repair.py is running")
    setup_discord()
    handle_deluge_verification()
    check_plex_external_status()


main()
