"""
cloud_role_switcher.py — Pure Headless Lilith Cloud Active Role Switcher
========================================================================

Switches the active character for an account directly on Lilith's cloud servers
(rocdir.lilithgame.com) over HTTPS in milliseconds, completely bypassing the UI/ADB.
"""
import ssl
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

ROCDIR_HOST = "https://rocdir.lilithgame.com"
DEFAULT_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 14; 2311DRK48C_Simulator Build/UP1A.231005.007)"

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

def get_cloud_roles(
    app_uid: str,
    app_token: str,
    udid: str = "F682A5114F7DD6AD7995F8ED2D6719BA",
    app_id: int = 2104267,
    client_ip: str = "194.176.99.80"
) -> List[Dict[str, Any]]:
    """
    Fetch all characters associated with this account from Lilith Cloud directory.
    """
    params = {
        "app_uid": str(app_uid),
        "app_token": str(app_token),
        "app_id": str(app_id),
        "lg_channel": "and",
        "sdk_type": "1",
        "ip": str(client_ip),
        "udid": str(udid),
        "lang": "en",
        "platform": "android",
        "ignoreserverlist": "true"
    }
    url = f"{ROCDIR_HOST}/get/roles?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as r:
        raw = r.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)

    players = []
    for region_id, reg_data in data.items():
        if isinstance(reg_data, dict) and "Players" in reg_data:
            players.extend(reg_data["Players"])
    return players

import time

_LAST_SWITCH_TIME = 0.0
_MIN_SWITCH_PACING = 2.5

def switch_cloud_active_role(
    role_id: int,
    server_id: int,
    app_uid: str,
    app_token: str,
    udid: str = "F682A5114F7DD6AD7995F8ED2D6719BA",
    app_id: int = 2104267,
    client_ip: str = "194.176.99.80",
    region_id: int = 1
) -> bool:
    """
    Switch the account's active role on Lilith Cloud to the target role_id.
    Subsequent TCP logins via Opcode 14 will immediately load this role.
    Applies 2.5s pacing delay and 3s retry loop to eliminate edge CDN rate limits.
    """
    global _LAST_SWITCH_TIME
    now = time.time()
    elapsed = now - _LAST_SWITCH_TIME
    if elapsed < _MIN_SWITCH_PACING:
        time.sleep(_MIN_SWITCH_PACING - elapsed)

    params = {
        "app_uid": str(app_uid),
        "app_token": str(app_token),
        "app_id": str(app_id),
        "lg_channel": "and",
        "sdk_type": "1",
        "ip": str(client_ip),
        "udid": str(udid),
        "lang": "en",
        "region_id": str(region_id),
        "player_id": str(role_id),
        "server_id": str(server_id)
    }
    url = f"{ROCDIR_HOST}/login/role?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})

    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as r:
                res = json.loads(r.read().decode("utf-8", errors="ignore"))
                success = res.get("success", False) or res.get("errorType") == 0
                already_active = res.get("errorType") == 241
                if success:
                    _LAST_SWITCH_TIME = time.time()
                    print(f"    [CLOUD SWITCH SUCCESS] Active character set to Role {role_id} (Server {server_id}).")
                    return True
                elif already_active:
                    _LAST_SWITCH_TIME = time.time()
                    print(f"    [CLOUD SWITCH CONFIRMED] Role {role_id} is already the active character on Lilith Cloud.")
                    return True
                else:
                    print(f"    [CLOUD SWITCH NOTICE] Attempt {attempt} server response: {res}")
        except Exception as e:
            print(f"    [CLOUD SWITCH NOTICE] Attempt {attempt} request failed: {e}")

        if attempt < 2:
            print("    [CLOUD SWITCH PACING] Waiting 3.0s before retry...")
            time.sleep(3.0)

    _LAST_SWITCH_TIME = time.time()
    print(f"    [CLOUD SWITCH FAILED] Unable to switch role {role_id} after 2 attempts.")
    return False

def ensure_character_active(char: dict) -> bool:
    """
    Convenience wrapper to ensure a character from accounts_fleet.json is active.
    """
    role_id = int(char.get("role_id", 0))
    server_id = int(char.get("kingdom_id") or char.get("server_id", 0))
    app_uid = str(char.get("app_uid", ""))
    app_token = str(char.get("access_token") or char.get("app_token") or "")
    udid = str(char.get("device_udid") or char.get("udid") or "F682A5114F7DD6AD7995F8ED2D6719BA")
    app_id = int(char.get("server_id_int", 2104267))
    char_name = char.get("name", str(role_id))

    print(f"\n[FLEET] Switching Lilith Cloud state to {char_name} (Role {role_id}, Server {server_id})...")
    return switch_cloud_active_role(
        role_id=role_id,
        server_id=server_id,
        app_uid=app_uid,
        app_token=app_token,
        udid=udid,
        app_id=app_id
    )

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "python")
    from fleet_manager import load_fleet
    fleet = load_fleet()
    print("Testing get_cloud_roles:")
    roles = get_cloud_roles(fleet[0]["app_uid"], fleet[0]["access_token"])
    for r in roles:
        print(f"  Role ID: {r.get('PlayerId')} | Name: {r.get('PlayerName')} | Server: {r.get('ServerId')} | Power: {r.get('Power'):,}")
