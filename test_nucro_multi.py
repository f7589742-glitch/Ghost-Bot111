import sys
import asyncio
import json
import logging

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.lilith_cloud import LilithCloudService
from cloud_role_switcher import switch_cloud_active_role
from app.services.combat_engine import CombatEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def main():
    target_name = "NUCROSHOP"
    role_id = 222157544

    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)

    target_acc = None
    target_char = None
    for acc in fleet:
        for c in acc.get('characters', []):
            if str(c.get('role_id')) == str(role_id) or c.get('name') == target_name:
                target_acc = acc
                target_char = c
                break
        if target_char:
            break

    if not target_char:
        print(f"Error: {target_name} not found in accounts_fleet.json!")
        return

    print("=" * 65)
    print(f"=== LAUNCHING 4-MARCH BARBARIAN HUNT ON {target_char['name']} (Role {role_id}) ===")
    print("=" * 65)

    sw = switch_cloud_active_role(
        role_id=int(role_id),
        server_id=3057,
        app_uid=str(target_acc['app_uid']),
        app_token=str(target_acc['access_token']),
        udid=str(target_acc['device_udid']),
        app_id=2104267
    )
    print(f"[SWITCH RESULT] Active character switch: {sw}")

    login_bytes = resolve_login_bytes({
        'role_id': int(role_id),
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

    result = await CombatEngine.execute_barbarian_hunt(
        target_role_id=int(role_id),
        kingdom_id=3057,
        gate_host=gate_host,
        gate_port=gate_port,
        app_uid=str(target_acc['app_uid']),
        app_token=str(target_acc['access_token']),
        udid=str(target_acc['device_udid']),
        character_name=target_char['name'],
        login_bytes=login_bytes,
        target_level=8,
        highest_barb_level="L8",
        skip_barbs_below="None",
        primary_commander="Auto",
        secondary_commander="None",
        combat_rounds=1,
        dispatch_all_marches=True,
        max_marches=4,
        heal_troops=True,
        log_callback=lambda msg: print(f"[LOG] {msg}", flush=True)
    )

    print("\n" + "=" * 65)
    print(f"=== FINAL 4-MARCH HUNT RESULT: {result} ===")
    print("=" * 65)

if __name__ == '__main__':
    asyncio.run(main())
