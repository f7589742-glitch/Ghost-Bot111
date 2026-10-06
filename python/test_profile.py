import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, build_minimal_login

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

print("Profile loaded:")
print("  app_uid:", profile["app_uid"])
print("  player_id:", profile.get("player_id", "N/A"))
print("  access_token:", profile["access_token"][:30] + "...")
print("  server:", profile["auth_server"] + ":" + str(profile["auth_port"]))

tokens = {
    "player_id": profile.get("player_id", profile["app_uid"]),
    "access_token": profile["access_token"],
    "app_uid": profile["app_uid"],
}

payload = build_minimal_login(tokens)
print("  login_payload:", len(payload), "bytes")
print("  login_payload_hex:", payload.hex()[:120] + "...")

decoded = ProtobufCodec.decode_message(payload)
print("  decoded:", decoded)
print("OK - login payload built successfully")
