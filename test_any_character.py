import sys, asyncio, json, zlib, struct, re
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames, CombatEngine
from app.services.lilith_cloud import LilithCloudService
from cloud_role_switcher import switch_cloud_active_role

async def test_char_combat(target_role_id):
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    
    target_acc = None
    target_char = None
    for acc in fleet:
        for c in acc.get('characters', []):
            if str(c.get('role_id')) == str(target_role_id):
                target_acc = acc
                target_char = c
                break
        if target_char: break

    if not target_char:
        print(f"Role {target_role_id} not found in fleet!")
        return

    print(f"\n=======================================================")
    print(f"=== TESTING COMBAT ON {target_char['name']} (Role {target_role_id}) ===")
    print(f"=======================================================")

    sw = switch_cloud_active_role(
        role_id=int(target_role_id),
        server_id=3057,
        app_uid=str(target_acc['app_uid']),
        app_token=str(target_acc['access_token']),
        udid=str(target_acc['device_udid']),
        app_id=2104267
    )
    print("Switch role result:", sw)

    login_bytes = resolve_login_bytes({
        'role_id': int(target_role_id),
        'app_token': target_acc['access_token'],
        'app_uid': target_acc['app_uid'],
        'udid': target_acc['device_udid'],
        'kingdom_id': 3057,
    })

    gate_host, gate_port = LilithCloudService.resolve_gateway(
        str(target_acc['app_uid']),
        str(target_acc['access_token']),
        str(target_acc['device_udid']),
        3057
    )

    res = await CombatEngine.execute_barbarian_hunt(
        target_role_id=int(target_role_id),
        kingdom_id=3057,
        gate_host=gate_host,
        gate_port=gate_port,
        app_uid=str(target_acc['app_uid']),
        app_token=str(target_acc['access_token']),
        udid=str(target_acc['device_udid']),
        character_name=target_char['name'],
        login_bytes=login_bytes,
        target_level=6,
        highest_barb_level="L6",
        skip_barbs_below="None",
        primary_commander="Auto",
        secondary_commander="None",
        combat_rounds=1,
        dispatch_all_marches=False,
        max_marches=1,
        heal_troops=True,
        log_callback=lambda msg: print(f"[LOG] {msg}", flush=True)
    )
    print("COMBAT RESULT:", res)

async def main():
    target_role = sys.argv[1] if len(sys.argv) > 1 else "222167622" # Default NucroShop6
    await test_char_combat(target_role)

if __name__ == '__main__':
    asyncio.run(main())
